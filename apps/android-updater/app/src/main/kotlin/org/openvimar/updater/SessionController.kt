package org.openvimar.updater

import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.openvimar.updater.core.*
import java.util.UUID

/** Process-owned command authority. Android services and Activities are only attachments. */
class SessionController(
    private val scope: CoroutineScope,
    private val store: SessionStore,
    private val packageLoader: suspend () -> ValidatedPackage?,
    private val operatorLoader: suspend () -> Boolean?,
    private val importer: suspend (String, () -> Unit, (() -> Unit) -> Unit) -> Unit,
    private val transportFactory: (ValidatedPackage) -> BleTransport,
    private val reportWriter: suspend (ValidatedPackage, Boolean?, String) -> Unit,
    private val reportReader: suspend () -> ByteArray,
    private val permissionCheck: () -> Boolean,
    private val reportExists: suspend () -> Boolean = { false },
    private val commonReleaseLoader:suspend ()->ValidatedCommonPackage? = {null},
    private val commonTargetSelector:suspend (String,()->Unit,((()->Unit)->Unit))->Unit = {_,_,_->error("Common target selection unavailable")},
    private val identityInspector:suspend (String,()->Unit)->RuntimeIdentity = {_,_->error("Runtime identity inspection unavailable")},
    private val bootstrapTargetLoader:suspend ()->BootstrapSelection? = {null},
    private val bootstrapRunner:suspend (Boolean,()->Unit,suspend(UpdateEvent)->Unit)->Unit = {_,_,_->error("Shared recovery preparation unavailable")},
    private val bootHistoryInspector:suspend (String,List<String>?,()->Unit)->BootHistoryObservation = {_,_,_->error("Recovery boot-history diagnostic unavailable")},
    private val bootHistoryReportWriter:suspend (BootHistoryDiagnosticReport)->Unit = {},
    private val diagnosticReportSelection:suspend (Boolean)->Unit = {},
    private val bootHistoryReportLoader:suspend ()->BootHistoryDiagnosticReport? = {null}
) {
    data class BootstrapSelection(val address:String,val resetUncertain:Boolean)
    private val mutableCommonBootstrapAvailable=MutableStateFlow(false)
    val commonBootstrapAvailable=mutableCommonBootstrapAvailable.asStateFlow()
    private val mutableBootstrapResetUncertain=MutableStateFlow(false)
    val bootstrapResetUncertain=mutableBootstrapResetUncertain.asStateFlow()
    data class ReportedIdentity(val address:String,val identity:RuntimeIdentity)
    private val mutableReportedIdentity=MutableStateFlow<ReportedIdentity?>(null)
    val reportedIdentity=mutableReportedIdentity.asStateFlow()
    /** Display/export snapshot only; this object grants no update or reset authority. */
    class ReportedBootHistory internal constructor(report:BootHistoryDiagnosticReport) {
        private val bytes=BootHistoryReports.encode(report)
        private val observed=requireNotNull(BootHistoryReports.decode(bytes).also{require(it.state==BootHistoryReadState.COMPLETE)}.observation)
        val address=observed.address
        val identity=observed.identity.copy(uid=java.util.Collections.unmodifiableList(observed.identity.uid.toList()))
        val history=observed.history.copy(entries=java.util.Collections.unmodifiableList(observed.history.entries.toList()))
        val observedAtMillis=observed.observedAtMillis
        val summary=BootHistoryReports.summary(history)
        fun reportBytes():ByteArray=bytes.copyOf()
    }
    private val mutableReportedBootHistory=MutableStateFlow<ReportedBootHistory?>(null)
    val reportedBootHistory=mutableReportedBootHistory.asStateFlow()
    @Volatile var lastBootHistoryAddress:String?=null
        private set
    @Volatile var lastBootHistoryMessage:String?=null
        private set
    private fun historyStatus(message:String) {synchronized(lock){lastBootHistoryMessage=message;mutableStatus.value=message}}
    data class ResumeOffer(val id: String, val needsConfirmation: Boolean)
    private data class Authority(val offer: ResumeOffer, val digest: String, val address: String,
        val checkpoint: Checkpoint?, val revision: Long)
    private val lock = Any()
    private val coordinator = UpdateCoordinator()
    private val mutableBusy = MutableStateFlow(false)
    val busy = mutableBusy.asStateFlow()
    private val mutableStatus = MutableStateFlow("Import a ZIP package to begin, or choose Resume to continue a previous update.")
    val status = mutableStatus.asStateFlow()
    private val mutablePresentation = MutableStateFlow(SessionPresentation())
    val presentation = mutablePresentation.asStateFlow()
    private val mutableCommonReleasePending=MutableStateFlow(false)
    val commonReleasePending=mutableCommonReleasePending.asStateFlow()
    private var verifiedProbeIdentity: Pair<String, String>? = null
    @Volatile var running = false
        private set
    private var operation: Job? = null
    private var kind = ""
    private var revision = 0L
    private var generation = 0L
    private var authority: Authority? = null

    private fun launchCommand(command: String, result: CompletableDeferred<*>? = null, historyAddress:String?=null, block: suspend (Long) -> Unit): Boolean {
        val job: Job
        synchronized(lock) {
            if (mutableBusy.value) {
                // Lifecycle inspection is opportunistic and must not replace active progress/error text.
                if (command == "inspect") return false
                val current = when (kind) {
                    "import" -> "package import"
                    "update" -> "the update"
                    "probe" -> "the Bluetooth check"
                    else -> "the current operation"
                }
                mutableStatus.value = "Wait: $current is still in progress. No new operation was started."
                return false
            }
            // Correlation is installed before status/presentation emission and survives a rebind.
            if(command=="history"){
                lastBootHistoryAddress=historyAddress
                lastBootHistoryMessage="Reading recovery boot history. No device changes will be requested."
            }else if(command !in setOf("inspect","export")){lastBootHistoryAddress=null;lastBootHistoryMessage=null}
            mutableBusy.value = true
            kind = command
            mutablePresentation.value = mutablePresentation.value.copy(busy = true, progressPercent = null, operation = when(command) {
                "inspect", "history" -> SessionOperation.INSPECT
                "import" -> SessionOperation.IMPORT
                "probe", "target", "identity" -> SessionOperation.PROBE
                "update", "bootstrap", "fleet" -> SessionOperation.UPDATE
                "prepare" -> SessionOperation.PREPARE
                "export" -> SessionOperation.EXPORT
                "operator" -> SessionOperation.OPERATOR
                else -> SessionOperation.IDLE
            })
            if (command == "probe" || command == "update") {
                verifiedProbeIdentity = null
                mutablePresentation.value = mutablePresentation.value.copy(bluetoothVerified = false, observedMainHash = null)
            }
            if(command in setOf("target","identity")) mutableReportedIdentity.value=null
            if(command=="history")mutableReportedBootHistory.value=null
            running = command in setOf("update","probe","target","identity","bootstrap","fleet","history")
            if (command == "update") mutableStatus.value = "Preparing update: checking the package and saved progress…"
            if (command == "probe") mutableStatus.value = "Bluetooth check: preparing. No firmware will be uploaded."
            val acceptedGeneration = ++generation
            job = scope.launch(start = CoroutineStart.LAZY) {
                var commandFailed = false
                try {
                    // A newer explicit operation owns report chronology, including failures.
                    // Lifecycle refresh/export does not silently change the selected report.
                    if(command !in setOf("inspect","export"))diagnosticReportSelection(false)
                    block(acceptedGeneration)
                } catch (failure: CancellationException) {
                    commandFailed = true
                    if(command=="history")historyStatus("History read stopped. No device changes were requested; export the diagnostic attempt.")
                    else mutableStatus.value = "Operation stopped. Data preserved; an explicit action is required to continue."
                } catch (failure: Exception) {
                    commandFailed = true
                    if(command=="history")historyStatus("Paused: ${UpdateCopy.failure(failure.message)}")
                    else mutableStatus.value = "Paused: ${UpdateCopy.failure(failure.message)}"
                } finally {
                    if (command in setOf("inspect", "import", "probe", "update", "operator", "target", "identity", "bootstrap")) {
                        withContext(NonCancellable) {
                            try { refreshEvidence() } catch (failure: Exception) {
                                synchronized(lock) {
                                    mutablePresentation.value = mutablePresentation.value.copy(inspected = true, loaded = false,
                                        hasCheckpoint = false, imagesVerified = false, resetAcknowledged = false,
                                        operatorOnline = null, bluetoothVerified = false, phase = null, progressPercent = null)
                                }
                                if (!commandFailed) mutableStatus.value = "Paused: ${UpdateCopy.failure(failure.message)}"
                            }
                        }
                    }
                }
            }
            operation = job
            job.invokeOnCompletion { failure ->
                synchronized(lock) {
                    if (operation === job) {
                        running = false
                        kind = ""
                        mutableBusy.value = false
                        mutablePresentation.value = mutablePresentation.value.copy(busy = false, operation = SessionOperation.IDLE)
                    }
                }
                if (result != null && !result.isCompleted) {
                    result.completeExceptionally(failure ?: CancellationException("Operation ended without a result"))
                }
            }
        }
        job.start()
        return true
    }

    /** Explicit local inspection; never connects, writes a checkpoint or grants reset authority. */
    fun inspect(): Boolean = launchCommand("inspect") { }
    fun refresh(): Boolean = inspect()

    /** Same process command gate for fleet and manual BLE. The caller supplies
     * the real coordinator operation, never a second independent radio owner.
     * Cancellation drains this exact operation before releasing the lease. */
    internal suspend fun <T> executeFleet(block:suspend(()->Unit)->T):T {
        val result=CompletableDeferred<T>()
        check(launchCommand("fleet",result){accepted->
            try {
                val coroutine=currentCoroutineContext()
                fun check(){coroutine.ensureActive();checkGeneration(accepted);check(permissionCheck()){"Bluetooth permissions missing or revoked"}}
                check();result.complete(block(::check))
            } catch(failure:Throwable){result.completeExceptionally(failure);throw failure}
        }){"Another Bluetooth/session operation is active; pause it before starting this group"}
        val owned=synchronized(lock){operation} ?: error("Bluetooth owner was not acquired")
        return try {result.await()}
        catch(cancelled:CancellationException){
            owned.cancel()
            // A firmware executor may return durable uncertain-reset evidence
            // after cancellation. Preserve that result after radio teardown.
            withContext(NonCancellable){owned.join();result.await()}
        }
        finally {withContext(NonCancellable){owned.join()}}
    }

    private suspend fun refreshEvidence() {
        // A diagnostic report belongs to the selected local identity, not to ZIP readability.
        // Clear first so a failed identity read never leaves stale export availability behind.
        synchronized(lock) { mutablePresentation.value = mutablePresentation.value.copy(reportAvailable = false) }
        val available = reportExists()
        synchronized(lock) { mutablePresentation.value = mutablePresentation.value.copy(reportAvailable = available) }
        bootHistoryReportLoader()?.takeIf{it.state==BootHistoryReadState.COMPLETE}?.let {mutableReportedBootHistory.value=ReportedBootHistory(it)}
        mutableCommonReleasePending.value=false
        mutableCommonReleasePending.value=commonReleaseLoader()!=null
        mutableCommonBootstrapAvailable.value=false;mutableBootstrapResetUncertain.value=false
        bootstrapTargetLoader()?.let {mutableCommonBootstrapAvailable.value=true;mutableBootstrapResetUncertain.value=it.resetUncertain}
        val pkg = packageLoader()
        if (pkg == null) {
            synchronized(lock) {
                verifiedProbeIdentity = null
                mutablePresentation.value = SessionPresentation(inspected = true, loaded = true,
                    busy = mutableBusy.value, operation = mutablePresentation.value.operation,
                    reportAvailable = available)
            }
            return
        }
        val summary = PackageSummary.from(pkg)
        val identity = pkg.bundleDigest to pkg.manifest.device.bleAddress
        synchronized(lock) {
            if (verifiedProbeIdentity != identity) {
                verifiedProbeIdentity = null
                mutablePresentation.value = mutablePresentation.value.copy(observedMainHash = null)
            }
            mutablePresentation.value = mutablePresentation.value.copy(packageSummary = summary,
                bluetoothVerified = verifiedProbeIdentity == identity)
        }
        val checkpoint = store.load(pkg.bundleDigest, pkg.manifest.device.bleAddress,pkg.targetUid)
        require(checkpoint == null || UpdatePlanner.matches(pkg, checkpoint)) { "Session identity/schema mismatch" }
        val evidence = SessionEvidence.from(checkpoint)
        val operator = operatorLoader()
        val progress = when(checkpoint?.phase) {
            Phase.UPLOAD_MIGRATION -> (checkpoint.ackOffset * 100L / pkg.migration.size).toInt().coerceIn(0, 100)
            Phase.UPLOAD_MAIN -> (checkpoint.ackOffset * 100L / pkg.main.size).toInt().coerceIn(0, 100)
            else -> null
        }
        synchronized(lock) {
            mutablePresentation.value = mutablePresentation.value.copy(inspected = true, loaded = true,
                packageSummary = summary, hasCheckpoint = checkpoint != null, imagesVerified = evidence.imagesVerified,
                resetAcknowledged = evidence.resetAcknowledged, operatorOnline = operator,
                bluetoothVerified = verifiedProbeIdentity == identity, reportAvailable = available,
                phase = checkpoint?.phase, progressPercent = progress)
        }
    }

    private fun presentEvent(event: UpdateEvent) {
        synchronized(lock) {
            val phase = when(event) {
                is UpdateEvent.Progress -> event.phase
                is UpdateEvent.Planned -> when(event.decision) {
                    Decision.UploadMigration -> Phase.UPLOAD_MIGRATION
                    Decision.RunMigration -> Phase.MIGRATION_RESET_INTENT
                    Decision.UploadMain -> Phase.UPLOAD_MAIN
                    Decision.ReturnToMain -> Phase.FINAL_RESET_INTENT
                    Decision.AwaitOperator -> Phase.AWAIT_OPERATOR
                    Decision.Reject -> null
                }
                is UpdateEvent.AwaitingOperator -> Phase.AWAIT_OPERATOR
                else -> mutablePresentation.value.phase
            }
            mutablePresentation.value = mutablePresentation.value.copy(phase = phase,
                progressPercent = if(event is UpdateEvent.Progress) (event.acknowledgedOffset * 100L / event.total).toInt().coerceIn(0,100) else null)
        }
    }

    private fun checkGeneration(expected: Long) {
        synchronized(lock) { check(generation == expected) { "Operation stopped" } }
    }

    /** Explicit diagnostic action: reads states only, never saves a checkpoint or sends a reset/upload. */
    fun probe(): Boolean = launchCommand("probe") { accepted ->
        val pkg = packageLoader() ?: error("Import the signed ZIP package for this dimmer first.")
        var transport: BleTransport? = null
        var operator: Boolean? = null
        try {
            checkGeneration(accepted)
            check(permissionCheck()) { "Bluetooth permissions missing. Choose Allow Bluetooth, then retry." }
            operator = operatorLoader()
            val checkpoint = store.load(pkg.bundleDigest, pkg.manifest.device.bleAddress,pkg.targetUid)
            val opened = transportFactory(pkg)
            transport = opened
            mutableStatus.value = "Bluetooth check: connecting to the dimmer. If Android asks for pairing, complete the system request and wait. No firmware will be installed."
            opened.connect(pkg.manifest.device.bleAddress)
            checkGeneration(accepted)
            check(permissionCheck()) { "Bluetooth permissions revoked. Choose Allow Bluetooth, then retry." }
            if(pkg.runtimeIdentity!=null) {
                val identity=RuntimeIdentityLookup.forRelease(opened,requireNotNull(pkg.commonManifest))
                require(identity==pkg.runtimeIdentity) {"Runtime identity changed; select the target again"}
            }
            val remote = opened.images()
            checkGeneration(accepted)
            check(UpdatePlanner.next(pkg, remote, checkpoint) != Decision.Reject) {
                "Bluetooth connected, but the installed firmware does not match this package. No update performed. Export the report."
            }
            synchronized(lock) {
                verifiedProbeIdentity = pkg.bundleDigest to pkg.manifest.device.bleAddress
                mutablePresentation.value = mutablePresentation.value.copy(observedMainHash = remote.primary?.hash)
            }
            mutableStatus.value = "Bluetooth check succeeded. Secure connection and recognised firmware; no update performed. You can start or resume the update."
        } catch (failure: CancellationException) {
            mutableStatus.value = "Bluetooth check stopped. No update performed."
            throw failure
        } catch (failure: Exception) {
            mutableStatus.value = "Paused: ${UpdateCopy.failure(failure.message)}"
        } finally {
            withContext(NonCancellable) {
                try { transport?.close() } finally { reportWriter(pkg, operator, mutableStatus.value) }
            }
        }
    }

    fun start(resume: Boolean, offerId: String? = null, confirmed: Boolean = false): Boolean = launchCommand("update") { accepted ->
        // All potentially failing IO happens inside admission's finally, before any transport exists.
        check(permissionCheck()) { "Bluetooth permissions missing. Choose Allow Bluetooth, then retry." }
        val pkg = packageLoader() ?: error("Import the signed ZIP package for this dimmer first.")
        val checkpoint = store.load(pkg.bundleDigest, pkg.manifest.device.bleAddress,pkg.targetUid)
        val operator = operatorLoader()
        val uncertain = SessionEvidence.from(checkpoint).needsResetConfirmation
        val selectedAuthority = synchronized(lock) {
            val candidate = authority
            authority = null // Offers are one-use, including rejected attempts.
            candidate
        }
        if (resume) {
            check(selectedAuthority != null && selectedAuthority.offer.id == offerId &&
                selectedAuthority.digest == pkg.bundleDigest && selectedAuthority.address == pkg.manifest.device.bleAddress &&
                selectedAuthority.checkpoint == checkpoint && selectedAuthority.revision == revision) { "Confirmation expired: choose Resume again" }
            check(!uncertain || confirmed) { "Confirmation required: choose Resume and review the restart request." }
        } else {
            check(checkpoint == null && !confirmed && offerId == null) { "Session saved: choose Resume to check and continue the update." }
        }
        checkGeneration(accepted)
        check(permissionCheck()) { "Bluetooth permissions revoked. Choose Allow Bluetooth, then retry." }
        running = true
        try {
            val transport = transportFactory(pkg)
            fun checkSubmission() {
                checkGeneration(accepted)
                check(permissionCheck()) { "Bluetooth permissions revoked. Choose Allow Bluetooth, then retry." }
            }
            val guarded = object : BleTransport,MigrationBootTransport {
                override suspend fun connect(address: String) {
                    checkSubmission()
                    mutableStatus.value = "Connecting to the dimmer… If Android asks for pairing, complete the system request and wait for the result here. Choose Resume only if the operation is interrupted."
                    transport.connect(address)
                    mutableStatus.value = "Connection established. Checking installed firmware…"
                }
                override suspend fun identity():RuntimeIdentity {checkSubmission();return transport.identity()}
                override suspend fun identityV2():RuntimeIdentity {checkSubmission();return transport.identityV2()}
                override suspend fun images(): RemoteImages { checkSubmission(); return transport.images() }
                override suspend fun upload(data: ByteArray, onAck: suspend (Int) -> Unit) {
                    checkSubmission()
                    transport.upload(data) { offset -> checkSubmission(); onAck(offset) }
                }
                override suspend fun reset(): ResetAck { checkSubmission(); return transport.reset() }
                override suspend fun bootMigration(expectedHash:String):ResetAck {checkSubmission();return (transport as? MigrationBootTransport ?: error("Migration boot transport unavailable")).bootMigration(expectedHash)}
                override suspend fun close() = transport.close()
            }
            coordinator.run(pkg, guarded, store, allowResetRetry = resume && uncertain && confirmed) { event ->
                presentEvent(event)
                mutableStatus.value = describe(event)
                reportWriter(pkg, operator, mutableStatus.value)
            }
        } finally {
            reportWriter(pkg, operator, mutableStatus.value)
        }
    }

    suspend fun prepareResume(): ResumeOffer {
        val result = CompletableDeferred<ResumeOffer>()
        check(launchCommand("prepare", result) { accepted ->
            try {
                val pkg = packageLoader() ?: error("Import the signed ZIP package for this dimmer first.")
                val checkpoint = store.load(pkg.bundleDigest, pkg.manifest.device.bleAddress,pkg.targetUid)
                checkGeneration(accepted)
                val offer = ResumeOffer(UUID.randomUUID().toString(), SessionEvidence.from(checkpoint).needsResetConfirmation)
                synchronized(lock) {
                    checkGeneration(accepted)
                    authority = Authority(offer, pkg.bundleDigest, pkg.manifest.device.bleAddress, checkpoint, revision)
                }
                result.complete(offer)
            } catch (failure: Throwable) {
                result.completeExceptionally(failure)
                throw failure
            }
        }) { "Wait for the current operation to finish" }
        val value = result.await()
        awaitIdle()
        return value
    }

    fun importDocument(source: String): Boolean = launchCommand("import") { accepted ->
        val context = currentCoroutineContext()
        val checkActive = { context.ensureActive(); checkGeneration(accepted) }
        importer(source, checkActive) { commit ->
            synchronized(lock) {
                checkActive()
                commit()
                revision++
                authority = null
            }
        }
        checkActive()
        mutableStatus.value = if(commonReleaseLoader()!=null) "Common release verified and saved. Choose a Bluetooth dimmer; its identity will be read from the device."
            else "Package verified and saved. Choose Check Bluetooth for a read-only check, Start update to begin, or Resume for a previous session."
    }

    /** Read a candidate directly; optional fleet organisation is a separate user action. */
    fun inspectIdentity(address:String):Boolean = launchCommand("identity") {accepted ->
        val context=currentCoroutineContext()
        val checkActive={context.ensureActive();checkGeneration(accepted);check(permissionCheck()) {"Bluetooth permissions missing or revoked"}}
        checkActive()
        require(Regex("([0-9A-F]{2}:){5}[0-9A-F]{2}").matches(address)) {"Invalid selected Bluetooth address"}
        mutableStatus.value="Connecting to the selected dimmer to read its identity. Complete Android pairing if requested."
        val observed=identityInspector(address,checkActive);checkActive()
        RuntimeIdentityLookup.validate(observed)
        mutableReportedIdentity.value=ReportedIdentity(address,observed)
        mutableStatus.value="Dimmer identity read over authenticated Bluetooth. You can save its name and room; no firmware installed."
    }

    /** Explicit authenticated READ only. Does not load a ZIP, checkpoint or update plan. */
    fun inspectBootHistory(address:String,expectedUid:List<String>?=null):Boolean {
        val pinned=expectedUid?.toList()
        return launchCommand("history",historyAddress=address) {accepted ->
            val context=currentCoroutineContext()
            val checkActive={context.ensureActive();checkGeneration(accepted);check(permissionCheck()){"Bluetooth permissions missing or revoked"}}
            require(Regex("([0-9A-F]{2}:){5}[0-9A-F]{2}").matches(address)){"Invalid selected Bluetooth address"}
            require(pinned==null||(pinned.size==2&&pinned.all{Regex("[0-9a-f]{8}").matches(it)})){"Invalid expected dimmer UID"}
            val started=System.currentTimeMillis()
            val attempt=BootHistoryDiagnosticReport(UUID.randomUUID().toString(),address,pinned,BootHistoryReadState.READING,started,null,null)
            bootHistoryReportWriter(attempt)
            try {
                checkActive()
                historyStatus("Reading recovery boot history. Complete Android pairing if requested; no device changes will be requested.")
                val observed=bootHistoryInspector(address,pinned,checkActive);checkActive()
                BootHistoryReports.validateObservation(observed)
                require(observed.address==address&&(pinned==null||observed.identity.uid==pinned)){"Runtime history identity differs from the selected dimmer"}
                val completed=attempt.copy(state=BootHistoryReadState.COMPLETE,finishedAtMillis=System.currentTimeMillis().coerceAtLeast(observed.observedAtMillis),observation=observed)
                bootHistoryReportWriter(completed);checkActive()
                synchronized(lock){checkGeneration(accepted);mutableReportedBootHistory.value=ReportedBootHistory(completed)}
                historyStatus(requireNotNull(mutableReportedBootHistory.value).summary)
            }catch(cancelled:CancellationException){
                withContext(NonCancellable){bootHistoryReportWriter(attempt.copy(state=BootHistoryReadState.CANCELLED,finishedAtMillis=System.currentTimeMillis().coerceAtLeast(started)))}
                throw cancelled
            }catch(failure:Exception){
                val unsupported=failure is BootHistoryUnavailable||failure is IdentityCommandUnavailable
                bootHistoryReportWriter(attempt.copy(state=if(unsupported)BootHistoryReadState.UNSUPPORTED else BootHistoryReadState.FAILED,finishedAtMillis=System.currentTimeMillis().coerceAtLeast(started)))
                historyStatus(if(unsupported)"Recovery boot history is unsupported by this firmware. No device changes were requested; the attempt was saved."
                    else "Recovery history could not be accepted. No device changes were requested. ${UpdateCopy.failure(failure.message)}")
            }finally{
                withContext(NonCancellable){mutablePresentation.value=mutablePresentation.value.copy(reportAvailable=reportExists())}
            }
        }
    }

    /** Explicit read-only selection. No upload, reset or registration is performed. */
    fun selectCommonTarget(address:String):Boolean = launchCommand("target") {accepted ->
        check(permissionCheck()) {"Bluetooth permissions missing"}
        val context=currentCoroutineContext()
        val checkActive={context.ensureActive();checkGeneration(accepted);check(permissionCheck()) {"Bluetooth permissions revoked"}}
        mutableStatus.value="Connecting to the selected dimmer to read its identity and compatibility…"
        commonTargetSelector(address,checkActive) {commit ->
            synchronized(lock){checkActive();commit();revision++;authority=null}
        }
        packageLoader()?.runtimeIdentity?.let {mutableReportedIdentity.value=ReportedIdentity(address,it)}
        mutableStatus.value=if(bootstrapTargetLoader()!=null) "Legacy recovery recognised by exact signed image hashes. UID and loader are not yet observable. Choose Prepare dimmer for this release; the signed helper validates compatibility on the dimmer."
            else "Dimmer identified and compatible with the common release. No firmware installed. Choose Start update or Resume."
    }

    /** Explicit legacy bridge; the runner can upload MIGRATION only until identity adoption. */
    fun startCommonBootstrap(allowResetRetry:Boolean=false):Boolean=launchCommand("bootstrap") {accepted ->
        val selected=bootstrapTargetLoader() ?: error("Choose a compatible legacy Bluetooth dimmer first")
        check(!allowResetRetry || selected.resetUncertain) {"No uncertain recovery restart to confirm"}
        val context=currentCoroutineContext()
        val checkActive={context.ensureActive();checkGeneration(accepted);check(permissionCheck()) {"Bluetooth permissions missing or revoked"}}
        checkActive();authority=null
        mutableStatus.value="Preparing independent Bluetooth recovery. The signed helper checks the actual loader before changing recovery; device identity will be read afterwards."
        var paused=false
        bootstrapRunner(allowResetRetry,checkActive){event->
            checkActive();if(event is UpdateEvent.Paused || event is UpdateEvent.Stopped)paused=true
            presentEvent(event);mutableStatus.value=describe(event)
        }
        checkActive()
        if(!paused && packageLoader()?.runtimeIdentity!=null) {
            mutableStatus.value="Recovery prepared and runtime identity verified. Choose Start update or Resume to install the firmware."
            mutableReportedIdentity.value=null
            packageLoader()?.let {reportWriter(it,null,mutableStatus.value)}
        }
    }

    fun stop() {
        synchronized(lock) {
            generation++
            authority = null
            coordinator.stop()
            if (kind != "update") operation?.cancel()
        }
        mutableStatus.value = "Stop requested. An internal copy or restart already started may finish. Saved progress remains available."
    }

    fun notifyFailure(message: String) { mutableStatus.value = "Paused: ${UpdateCopy.failure(message)}" }

    fun detachUpdateHost() {
        synchronized(lock) { if (kind in setOf("update","probe","target","identity","bootstrap","history")) stop() }
    }

    fun confirmOperator(online: Boolean): Boolean = launchCommand("operator") { accepted ->
        val pkg = packageLoader() ?: error("Import a ZIP package before recording the result.")
        val checkpoint = store.load(pkg.bundleDigest, pkg.manifest.device.bleAddress,pkg.targetUid)
        check(SessionEvidence.from(checkpoint).imagesVerified) { "First verify the firmware using Start update or Resume, then record the result." }
        checkGeneration(accepted)
        val outcome = if (online) "Result recorded: you confirmed the dimmer is online."
            else "Result recorded: you reported that the dimmer did not return online. Export the report for diagnosis."
        reportWriter(pkg, online, outcome)
        mutableStatus.value = outcome
    }

    suspend fun report(): ByteArray {
        val result = CompletableDeferred<ByteArray>()
        check(launchCommand("export", result) {
            try { result.complete(reportReader()) } catch (failure: Throwable) { result.completeExceptionally(failure); throw failure }
        }) { "Wait for the current operation to finish" }
        val value = result.await()
        awaitIdle()
        return value
    }

    suspend fun awaitIdle() { synchronized(lock) { operation }?.join() }

    private fun describe(event: UpdateEvent): String = UpdateCopy.describe(event)
}
