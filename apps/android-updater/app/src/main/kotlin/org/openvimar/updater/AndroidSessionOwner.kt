package org.openvimar.updater

import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.util.AtomicFile
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject
import org.openvimar.updater.ble.NordicBleTransport
import org.openvimar.updater.ble.BleDiagnostics
import org.openvimar.updater.core.*
import java.io.File

/** One process owner, retaining no Activity or Service. Service recreation cannot replace its gate. */
internal object AndroidSessionOwner {
    @Volatile private var owner: SessionController? = null

    /** Instrumentation seam; the replacement must be idle and uses no production radio by itself. */
    @Synchronized internal fun installForTest(replacement: SessionController?) {
        check(owner?.busy?.value != true) { "An owner is still active" }
        owner = replacement
    }

    @Synchronized fun get(context: Context): SessionController {
        owner?.let { return it }
        val app = context.applicationContext
        val files = SessionFiles(app.filesDir)
        val store = AndroidSessionStore(app.filesDir)
        val documents = DocumentRepository(app)
        val bootstrapStore=AndroidBootstrapStore(app.filesDir)
        val bootHistoryStore=BootHistoryReportStore(app.filesDir)
        val bootstrapCoordinator=CommonBootstrapCoordinator()
        fun selectedReport():File? {
            bootHistoryStore.selectedFile()?.let{return it}
            files.current()?.let{return files.report(it)}
            val address=documents.pendingLegacyTarget() ?: return null
            val common=documents.pendingCommon() ?: return null
            return bootstrapStore.reportFile(common.bundleDigest,address)
        }
        fun reportFile(): File = selectedReport() ?: error("No diagnostic report is available")
        val controller = SessionController(
            CoroutineScope(SupervisorJob() + Dispatchers.IO), store,
            { documents.current() },
            {
                val file = reportFile()
                if (!file.exists() && !File(file.path + ".bak").exists()) null
                else JSONObject(AtomicFile(file).openRead().use { it.readBytes().toString(Charsets.UTF_8) }).let {
                    if (it.isNull("operatorOnlineConfirmation")) null else it.getBoolean("operatorOnlineConfirmation")
                }
            },
            { source, checkActive, commit -> documents.importAnyDocument(Uri.parse(source), checkActive, commit) },
            { pkg -> NordicBleTransport(app, pkg.manifest.device.bleAddress) },
            { pkg, operator, outcome ->
                val checkpoint = store.load(pkg.bundleDigest, pkg.manifest.device.bleAddress,pkg.targetUid)
                val evidence = SessionEvidence.from(checkpoint)
                val identity = SessionFiles.Identity(pkg.bundleDigest, pkg.manifest.device.bleAddress,pkg.targetUid)
                val json = JSONObject().put("package", pkg.bundleDigest).put("bundleId", pkg.manifest.bundleId)
                    .put("device", JSONObject().put("name", pkg.manifest.device.name).put("ieee", pkg.manifest.device.ieee)
                        .put("uid", JSONArray(pkg.manifest.device.uid)).put("bleAddress", pkg.manifest.device.bleAddress))
                    .put("identityEvidence",if(pkg.runtimeIdentity!=null) "authenticated BLE reported identity; not hardware attestation" else "signed device-bound schema1 descriptor")
                    .put("imagesVerified", evidence.imagesVerified).put("resetAcknowledged", evidence.resetAcknowledged)
                    .put("operatorOnlineConfirmation", operator ?: JSONObject.NULL).put("outcome", outcome)
                    .put("androidApi", Build.VERSION.SDK_INT)
                    .put("androidRelease", Build.VERSION.RELEASE)
                    .put("appVersion", app.packageManager.getPackageInfo(app.packageName, 0).versionName)
                    .put("bleDiagnostic", JSONArray(BleDiagnostics.snapshot(pkg.manifest.device.bleAddress).map { JSONObject(it) }))
                val atomic = AtomicFile(files.report(identity))
                val output = atomic.startWrite()
                try {
                    output.write(json.toString(2).toByteArray())
                    atomic.finishWrite(output)
                } catch (failure: Throwable) {
                    atomic.failWrite(output)
                    throw failure
                }
            },
            { AtomicFile(reportFile()).openRead().use { it.readBytes() } },
            { PermissionPolicy.required(Build.VERSION.SDK_INT).all { app.checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED } },
            {
                selectedReport()?.let {file -> file.exists() || File(file.path+".bak").exists()} ?: false
            },
            {documents.pendingCommon()},
            commonTargetSelector@{address,checkActive,commit ->
                require(Regex("([0-9A-F]{2}:){5}[0-9A-F]{2}").matches(address)) {"Invalid selected Bluetooth address"}
                val common=documents.pendingCommon() ?: error("Import a common release first")
                val transport=NordicBleTransport(app,address)
                try {
                    checkActive();transport.connect(address);checkActive()
                    val identity=try{RuntimeIdentityLookup.forRelease(transport,common.manifest)}catch(e:IdentityCommandUnavailable){
                        checkActive();val remote=transport.images();checkActive()
                        val checkpoint=bootstrapStore.load(common.bundleDigest,address)
                        require(CommonBootstrapCoordinator.eligible(common,address,remote,checkpoint)) {"Legacy recovery or source image is not authorized for this common release"}
                        documents.selectLegacyBootstrapTarget(address,checkActive,commit)
                        return@commonTargetSelector
                    };checkActive()
                    val previousBootstrap=bootstrapStore.load(common.bundleDigest,address)
                    require(previousBootstrap==null||CommonBootstrapCoordinator.matches(common,address,previousBootstrap)){"Previously saved bootstrap identity/schema mismatch"}
                    require(previousBootstrap?.observedUid==null || previousBootstrap.observedUid==identity.uid) {"Previously verified bootstrap UID changed"}
                    require(previousBootstrap?.observedIdentity==null || previousBootstrap.observedIdentity==identity){"Previously verified bootstrap loader/anchor identity changed"}
                    val bound=common.bind(identity,address)
                    val guarded=IdentityBoundTransport(transport,identity,common.manifest)
                    val remote=guarded.images();checkActive()
                    val checkpoint=store.load(bound.bundleDigest,address,bound.targetUid)
                    require(UpdatePlanner.next(bound,remote,checkpoint)!=Decision.Reject) {"Installed recovery or main is incompatible with this common release"}
                    documents.bindCommonTarget(address,identity,checkActive,commit)
                } finally {withContext(NonCancellable){transport.close()}}
            },
            {address,checkActive ->
                val transport=NordicBleTransport(app,address)
                try {checkActive();transport.connect(address);checkActive();RuntimeIdentityLookup.inspect(transport).also {checkActive()}}
                finally {withContext(NonCancellable){transport.close()}}
            },
            {
                documents.pendingLegacyTarget()?.let {address ->
                    val common=documents.pendingCommon() ?: error("Common release unavailable")
                    val checkpoint=bootstrapStore.load(common.bundleDigest,address)
                    SessionController.BootstrapSelection(address,checkpoint?.phase==BootstrapPhase.RESET_INTENT)
                }
            },
            {allowResetRetry,checkActive,onEvent ->
                val common=documents.pendingCommon() ?: error("Import a common release first")
                val address=documents.pendingLegacyTarget() ?: error("Choose a compatible legacy dimmer first")
                val native=NordicBleTransport(app,address)
                val transport=object:BleTransport,MigrationBootTransport {
                    override suspend fun connect(address:String){checkActive();native.connect(address);checkActive()}
                    override suspend fun identity():RuntimeIdentity {checkActive();return native.identity().also{checkActive()}}
                    override suspend fun identityV2():RuntimeIdentity {checkActive();return native.identityV2().also{checkActive()}}
                    override suspend fun images():RemoteImages {checkActive();return native.images().also{checkActive()}}
                    override suspend fun upload(data:ByteArray,onAck:suspend(Int)->Unit){checkActive();native.upload(data){offset->checkActive();onAck(offset)}}
                    override suspend fun reset():ResetAck {checkActive();return native.reset().also{checkActive()}}
                    override suspend fun bootMigration(expectedHash:String):ResetAck {checkActive();return native.bootMigration(expectedHash).also{checkActive()}}
                    override suspend fun close()=native.close()
                }
                try {bootstrapCoordinator.run(common,address,transport,bootstrapStore,{identity->
                    checkActive()
                    documents.bindCommonTarget(address,identity,checkActive){commit->checkActive();commit()}
                },allowResetRetry){event->
                    bootstrapStore.report(common.bundleDigest,address,event.toString());onEvent(event)
                }} finally {withContext(NonCancellable){bootstrapStore.report(common.bundleDigest,address,"Preparation command ended; inspect checkpoint and next explicit action")}}
            },
            bootHistoryInspector={address,expectedUid,checkActive ->
                val transport=NordicBleTransport(app,address)
                try {
                    checkActive();transport.connect(address);checkActive()
                    BootHistoryDiagnostic.read(address,transport,expectedUid,checkActive).also {observed ->
                        checkActive();BleDiagnostics.token(address)?.let{BleDiagnostics.bootHistory(it,observed.history)}
                    }
                } finally {withContext(NonCancellable){transport.close()}}
            },
            bootHistoryReportWriter={report->bootHistoryStore.save(report)},
            diagnosticReportSelection={selected->if(!selected)bootHistoryStore.deselect()},
            bootHistoryReportLoader={if(bootHistoryStore.selectedBytes()==null)null else bootHistoryStore.latest()}
        )
        owner = controller
        return controller
    }
}
