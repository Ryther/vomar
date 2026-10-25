package org.openvimar.updater.installer

import org.openvimar.installer.*
import org.openvimar.installer.resume.*
import java.io.IOException
import java.time.Instant
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean

internal data class InstallCaptureRequest(val requestId:String,val deviceName:String,val target:TargetIdentity,
    val reviewedReleaseSha256:String,val allowResetCatch:Boolean=false)
internal data class InstallOwnerReview(val requestId:String,val bindingId:String,val reviewedReleaseSha256:String)
internal enum class InitialInstallPhase {IDLE,CONNECTING,CAPTURING,AWAITING_EXPORT,AWAITING_REVIEW,AWAITING_RESUME_REVIEW,INSTALLING,VERIFIED_HALTED,STARTING,STARTED,CANCELLED,FAILED}
internal data class InitialInstallSnapshot(val phase:InitialInstallPhase=InitialInstallPhase.IDLE,val request:InstallCaptureRequest?=null,
    val binding:InstallBinding?=null,val archiveSha256:String?=null,val exportedDocument:String?=null,
    val mutationMayHaveStarted:Boolean=false,val commitMayHaveBeenWritten:Boolean=false,val resetCatchUsed:Boolean=false,
    val cpuDisposition:String="not observed",val journalFailure:Boolean=false,val message:String="No first installation is active",val candidate:Boolean=false,val debugStateUncertain:Boolean=false,
    val watchdog:ObservedWatchdogProfile?=null,val watchdogHandoff:String?=null,
    val resume:Boolean=false,val resumeHeadSha256:String?=null,val resumeFrontierPage:Int?=null,val resumeClassification:String?=null)
internal class InitialInstallReceipt private constructor(val binding:InstallBinding,val ficrSha256:String,val uicrSha256:String) {
    private val available=AtomicBoolean(true)
    fun consume(review:InstallOwnerReview){require(review.bindingId==binding.id&&review.reviewedReleaseSha256==binding.releaseSha256);check(available.compareAndSet(true,false)){"Verified start receipt already consumed"}}
    companion object {fun verified(binding:InstallBinding,original:OriginalMaterial,outcome:InstallOutcome):InitialInstallReceipt{
        require(outcome.verified);return InitialInstallReceipt(binding,original.ficrSha256,original.uicrSha256)}}
}
internal interface InitialInstallPersistence {
    /** Inspect retained private journals before opening/halt of this target. */
    fun assertCanCapture(target:TargetIdentity)
    /** Private immutable ZIP only after full equal passes and strict validation. */
    fun saveOriginal(requestId:String,archive:ByteArray)
    /** Immutable historical same-document export proof, before any FLASH intent. */
    fun saveExportReceipt(original:OriginalMaterial,binding:InstallBinding)
    /** Binding-specific start intent/acknowledgement, never execution approval. */
    fun recordStart(binding:InstallBinding,requestId:String,acknowledged:Boolean)
    /** Must be durable before returning; no memory bytes in this snapshot. */
    fun saveState(snapshot:InitialInstallSnapshot)
}
internal interface InitialInstallConnection:AutoCloseable {
    val lease:NrfInitialInstallLease
    val provenance:QuiescentProvenance
    /** Close physical USB and only then release its process-wide token. */
    override fun close()
}
internal class InitialInstallConnectionException(val cpuDisposition:String,cause:Exception,val resetCatchUsed:Boolean=false,val debugStateUncertain:Boolean=false,
    val watchdog:ObservedWatchdogProfile?=null,val watchdogHandoff:String?=null):IOException(cause.message,cause)

/** Serialized worker-owned state machine. The Activity owns neither USB nor
 * transaction lifetime. Every entry point is explicit, with no restored job,
 * automatic export, automatic install, CPU start or automatic repair. */
internal class InitialInstallController(private val connect:(InstallCaptureRequest,()->Boolean,InitialInstallReceipt?)->InitialInstallConnection,
    private val persistence:InitialInstallPersistence,private val journal:InstallJournalStore,
    private val resumeConnect:((InstallCaptureRequest,()->Boolean,(Long)->ResumeHardwareAuthority)->InitialInstallConnection)?=null,
    private val observed:(InitialInstallSnapshot)->Unit={}) {
    private val cancelled=AtomicBoolean(false)
    private var connection:InitialInstallConnection?=null
    private var original:VerifiedOriginal?=null;private var material:OriginalMaterial?=null
    private var reviewedResume:ReviewedResume?=null
    private var qualified:VerifiedCommonSet?=null;private var candidate:InspectedCommonCandidate?=null
    @Volatile var snapshot=InitialInstallSnapshot();private set
    var receipt:InitialInstallReceipt?=null;private set
    private fun stopped(){if(cancelled.get())throw IOException("Initial installation cancelled")}
    private fun publish(next:InitialInstallSnapshot){
        // Keep correlation/uncertainty even when persistence completed but its
        // acknowledgement failed. No target operation follows a thrown save.
        snapshot=next
        try{persistence.saveState(next)}catch(error:Exception){snapshot=next.copy(journalFailure=true);throw error}
        observed(next)
    }
    @Synchronized fun beginQualified(request:InstallCaptureRequest,release:VerifiedCommonSet){
        begin(request,release.releaseSha256,false){qualified=release}
    }
    @Synchronized fun beginCandidate(request:InstallCaptureRequest,release:InspectedCommonCandidate){
        begin(request,release.releaseSha256,true){candidate=release}
    }
    private fun begin(request:InstallCaptureRequest,releaseSha256:String,isCandidate:Boolean,retain:()->Unit){
        check(snapshot.phase==InitialInstallPhase.IDLE)
        require(UUID.fromString(request.requestId).toString()==request.requestId&&request.deviceName.isNotBlank()&&request.deviceName.length<=4096)
        require(request.reviewedReleaseSha256==releaseSha256){"The reviewed common artifact changed"}
        retain() // A cancellation received before this worker starts stays set.
        try {
            // Persist possible debug-halt ownership before the connector can
            // send DHCSR/reset. Process death never restarts this operation.
            publish(InitialInstallSnapshot(InitialInstallPhase.CONNECTING,request,message="Opening the explicitly reviewed USB target",candidate=isCandidate))
            persistence.assertCanCapture(request.target)
            stopped();val link=connect(request,cancelled::get,null);connection=link
            publish(snapshot.copy(phase=InitialInstallPhase.CAPTURING,resetCatchUsed=link.lease.resetCatchUsed,watchdog=link.lease.watchdogProfile,watchdogHandoff=link.lease.watchdogHandoff,
                cpuDisposition="last observed halted; exclusive connection retained",message="Capturing two complete quiescent original passes"))
            val started=Instant.now();val passes=mutableListOf<Map<String,ByteArray>>()
            repeat(2){
                stopped();require(link.lease.currentIdentity()==request.target)
                passes+=listOf("flash.bin","ficr.bin","uicr.bin").associateWith{file->stopped();link.lease.readOriginalRegion(file)}
                stopped();require(link.lease.currentIdentity()==request.target)
            }
            val archive=QuiescentArchive.create(passes[0],passes[1],link.provenance,started,Instant.now(),link.lease.originalCpuControl,link.lease.resetCatchUsed,link.lease.watchdogProfile)
            stopped();original=OriginalArchive.verify(archive);require(original?.identity==request.target)
            checkNotNull(original).requireFirstInstallCompatible() // Reject before labeling/publishing/exporting a new original.
            persistence.saveOriginal(request.requestId,archive);stopped()
            publish(snapshot.copy(phase=InitialInstallPhase.AWAITING_EXPORT,archiveSha256=original?.archiveSha256,message="Verified original ready: choose an explicit SAF export destination"))
        }catch(error:Exception){failed(error)}
    }
    @Synchronized fun export(port:ArchiveExport){
        check(snapshot.phase==InitialInstallPhase.AWAITING_EXPORT)
        try {
            stopped();val link=checkNotNull(connection);link.lease.currentIdentity()
            val exported=OriginalArchive.exportAndReopen(checkNotNull(original),port)
            stopped();link.lease.currentIdentity();val derived=exported.deriveOriginal()
            val binding=qualified?.let{InstallPlan.prepare(derived,it).binding}?:checkNotNull(candidate).previewBinding(derived)
            persistence.saveExportReceipt(derived,binding);stopped()
            material=derived
            publish(snapshot.copy(phase=InitialInstallPhase.AWAITING_REVIEW,binding=binding,exportedDocument=exported.document,
                message="Same-document export verified; review this exact original, release, UID and transaction before installation"))
        }catch(error:Exception){failed(error)}
    }
    @Synchronized fun prepareResumeQualified(request:InstallCaptureRequest,release:VerifiedCommonSet,original:ReopenedResumeOriginal,journal:FileResumeJournal,expectedHead:String){
        prepareResume(request,release.releaseSha256,false,original,journal,expectedHead){qualified=release}
    }
    @Synchronized fun prepareResumeCandidate(request:InstallCaptureRequest,release:InspectedCommonCandidate,original:ReopenedResumeOriginal,journal:FileResumeJournal,expectedHead:String){
        prepareResume(request,release.releaseSha256,true,original,journal,expectedHead){candidate=release}
    }
    private fun prepareResume(request:InstallCaptureRequest,releaseSha:String,isCandidate:Boolean,original:ReopenedResumeOriginal,journal:FileResumeJournal,expectedHead:String,retain:()->Unit){
        check(snapshot.phase==InitialInstallPhase.IDLE)
        require(UUID.fromString(request.requestId).toString()==request.requestId&&request.deviceName.isNotBlank()&&request.deviceName.length<=4096)
        require(request.reviewedReleaseSha256==releaseSha&&original.identity==request.target&&!request.allowResetCatch)
        retain()
        try{
            val derived=original.materialForPlan();material=derived
            publish(InitialInstallSnapshot(InitialInstallPhase.CONNECTING,request,archiveSha256=original.archiveSha256,
                exportedDocument=original.selectedDocument,mutationMayHaveStarted=true,commitMayHaveBeenWritten=true,candidate=isCandidate,resume=true,
                message="Preparing explicit repair from retained original; prior target state is uncertain"))
            stopped()
            val link=checkNotNull(resumeConnect){"Explicit resume connection is unavailable"}(request,cancelled::get){generation->
                val plan=qualified?.let{InstallPlan.prepare(derived,it)}?:checkNotNull(candidate).let{c->c.reviewOneBench(request.target,request.requestId,generation,request.reviewedReleaseSha256).use{c.preparePlan(derived,it,request.requestId,generation)}}
                val review=ReviewedResume.review(plan,original,journal,expectedHead,request.requestId,generation);reviewedResume=review
                review.hardwareAuthority()
            };connection=link;val review=checkNotNull(reviewedResume)
            stopped();require(link.lease.currentIdentity()==request.target)
            publish(snapshot.copy(phase=InitialInstallPhase.AWAITING_RESUME_REVIEW,binding=review.binding,
                resumeHeadSha256=review.journalHeadSha256,resumeFrontierPage=review.frontierPage,
                resumeClassification="Repair may rebuild known pages and reset custom settings; complete current reads determine verify-only, commit-only, or rebuild",
                watchdog=link.lease.watchdogProfile,watchdogHandoff=link.lease.watchdogHandoff,cpuDisposition="HALT retained for reviewed prior uncertainty",
                message="Original copy, signed release and retained journal match; review this exact repair before any FLASH write"))
        }catch(error:Exception){failed(error)}
    }
    @Synchronized fun resume(review:ResumeOwnerReview){
        check(snapshot.phase==InitialInstallPhase.AWAITING_RESUME_REVIEW)
        val prepared=checkNotNull(reviewedResume);val request=checkNotNull(snapshot.request)
        require(review.requestId==request.requestId&&review.bindingId==prepared.binding.id&&review.reviewedReleaseSha256==prepared.binding.releaseSha256&&review.journalHeadSha256==prepared.journalHeadSha256){"Fresh repair review does not match held request/binding/release/journal"}
        try{
            stopped();val link=checkNotNull(connection)
            publish(snapshot.copy(phase=InitialInstallPhase.INSTALLING,message="Explicit repair: validating all unissued original pages before bounded reconstruction"))
            val result=ExplicitResumeEngine().run(prepared,link.lease.authorizer(prepared.binding),::stopped);val outcome=result.outcome
            snapshot=snapshot.copy(mutationMayHaveStarted=outcome.mutationMayHaveStarted,commitMayHaveBeenWritten=outcome.commitMayHaveBeenWritten,journalFailure=outcome.journalFailure,
                resumeHeadSha256=result.journalHeadSha256?:snapshot.resumeHeadSha256,resumeClassification=result.mode?.name?:snapshot.resumeClassification)
            val disposition=closeConnection()
            publish(snapshot.copy(phase=if(outcome.verified)InitialInstallPhase.VERIFIED_HALTED else InitialInstallPhase.FAILED,cpuDisposition=disposition,message=outcome.message))
            if(outcome.verified)receipt=InitialInstallReceipt.verified(prepared.binding,checkNotNull(material),outcome)
            forgetMemory()
        }catch(error:Exception){failed(error)}
    }
    @Synchronized fun install(review:InstallOwnerReview){
        check(snapshot.phase==InitialInstallPhase.AWAITING_REVIEW)
        val request=checkNotNull(snapshot.request);val binding=checkNotNull(snapshot.binding)
        require(review.requestId==request.requestId&&review.bindingId==binding.id&&review.reviewedReleaseSha256==binding.releaseSha256){"Fresh owner review does not match this exact held transaction"}
        try {
            stopped();val link=checkNotNull(connection);link.lease.currentIdentity()
            val original=checkNotNull(material)
            val plan=qualified?.let{InstallPlan.prepare(original,it)}?:checkNotNull(candidate).let{c->
                c.reviewOneBench(request.target,request.requestId,link.lease.generation,review.reviewedReleaseSha256).use{permit->c.preparePlan(original,permit,request.requestId,link.lease.generation)}}
            require(plan.binding==binding)
            publish(snapshot.copy(phase=InitialInstallPhase.INSTALLING,message="Writing with durable intent and erased anchor commit until final verification"))
            val outcome=FirstInstallEngine().run(plan,link.lease.authorizer(binding),journal,::stopped)
            // Teardown itself can fail after commit acknowledgement. Preserve
            // the engine's uncertainty before entering that failure boundary.
            snapshot=snapshot.copy(mutationMayHaveStarted=outcome.mutationMayHaveStarted,
                commitMayHaveBeenWritten=outcome.commitMayHaveBeenWritten,journalFailure=outcome.journalFailure)
            val disposition=closeConnection()
            publish(snapshot.copy(phase=if(outcome.verified)InitialInstallPhase.VERIFIED_HALTED else InitialInstallPhase.FAILED,
                mutationMayHaveStarted=outcome.mutationMayHaveStarted,commitMayHaveBeenWritten=outcome.commitMayHaveBeenWritten,
                journalFailure=outcome.journalFailure,cpuDisposition=disposition,message=outcome.message))
            if(outcome.verified)receipt=InitialInstallReceipt.verified(binding,original,outcome)
            forgetMemory()
        }catch(error:Exception){failed(error)}
    }
    /** Non-blocking cancellation request; worker cleanup owns the connection. */
    fun cancel(){cancelled.set(true)}
    @Synchronized fun cancelAndClose(){
        cancel();if(connection==null){
            if(snapshot.phase==InitialInstallPhase.VERIFIED_HALTED){receipt=null;publish(snapshot.copy(phase=InitialInstallPhase.CANCELLED,message="Verified image deliberately left halted; no CPU start requested"))}
            return
        }
        val before=snapshot
        try {val disposition=closeConnection();publish(before.copy(phase=InitialInstallPhase.CANCELLED,cpuDisposition=disposition,
            mutationMayHaveStarted=snapshot.mutationMayHaveStarted,message="Cancelled; original export and transaction evidence retained"));forgetMemory()}
        catch(error:Exception){failed(error)}
    }
    private fun closeConnection():String {
        val link=connection?:return snapshot.cpuDisposition
        val mutated=link.lease.mutationMayHaveStarted
        // Capture uncertainty before resource teardown even if cleanup fails.
        snapshot=snapshot.copy(mutationMayHaveStarted=snapshot.mutationMayHaveStarted||mutated,resetCatchUsed=snapshot.resetCatchUsed||link.lease.resetCatchUsed,
            debugStateUncertain=snapshot.debugStateUncertain||link.lease.debugStateUncertain)
        connection=null
        try{link.lease.finish()}finally{link.close()}
        return if(link.lease.startMayHaveOccurred)"explicit verified reset/start may have occurred; no automatic retry"
            else if(link.lease.haltRetentionRequired)"halt retained after current/prior uncertainty; no CPU start requested"
            else if(link.lease.resetCatchUsed)"original RUN/HALT intent restored at stock reset vector; original PC was not resumed"
            else "original CPU debug control restored before any NVMC mutation"
    }
    @Synchronized fun startVerified(review:InstallOwnerReview){
        check(snapshot.phase==InitialInstallPhase.VERIFIED_HALTED)
        val request=checkNotNull(snapshot.request);val proof=checkNotNull(receipt)
        require(review.requestId==request.requestId&&review.bindingId==proof.binding.id&&review.reviewedReleaseSha256==proof.binding.releaseSha256)
        try{
            stopped();proof.consume(review);receipt=null
            publish(snapshot.copy(phase=InitialInstallPhase.STARTING,message="Rechecking complete verified image, UID and UICR before explicit reset/start"))
            persistence.recordStart(proof.binding,request.requestId,false);stopped()
            val link=connect(request,cancelled::get,proof);connection=link;link.lease.retainHaltForPriorUncertainty()
            publish(snapshot.copy(watchdog=link.lease.watchdogProfile,watchdogHandoff=link.lease.watchdogHandoff))
            require(link.lease.currentIdentity()==proof.binding.target)
            fun hash(bytes:ByteArray)=java.security.MessageDigest.getInstance("SHA-256").digest(bytes).joinToString(""){"%02x".format(it.toInt() and 255)}
            require(hash(link.lease.readOriginalRegion("ficr.bin"))==proof.ficrSha256&&hash(link.lease.readOriginalRegion("uicr.bin"))==proof.uicrSha256){"Verified target FICR/UICR changed"}
            require(hash(link.lease.readOriginalRegion("flash.bin"))==proof.binding.installedSha256){"Complete verified FLASH changed; CPU remains halted"}
            stopped();link.lease.startVerifiedReset();require(link.lease.startAcknowledged)
            persistence.recordStart(proof.binding,request.requestId,true)
            closeConnection();publish(snapshot.copy(phase=InitialInstallPhase.STARTED,cpuDisposition="new reset vector explicitly released after full receipt verification",
                message=if(snapshot.watchdog?.active==true)"Start acknowledged; signed loader waits for inherited watchdog reset before normal firmware. Physical qualification remains pending"
                    else "Explicit verified reset/start acknowledged; firmware/radio behavior still requires physical qualification"))
        }catch(error:Exception){failed(error)}
    }
    private fun failed(error:Exception){
        receipt=null
        if(error is InitialInstallConnectionException)snapshot=snapshot.copy(resetCatchUsed=snapshot.resetCatchUsed||error.resetCatchUsed,
            debugStateUncertain=snapshot.debugStateUncertain||error.debugStateUncertain,watchdog=error.watchdog?:snapshot.watchdog,watchdogHandoff=error.watchdogHandoff?:snapshot.watchdogHandoff)
        var disposition=if(error is InitialInstallConnectionException)error.cpuDisposition else snapshot.cpuDisposition
        var detail=(error.message?:error.javaClass.simpleName).take(1024)
        try{disposition=closeConnection()}catch(cleanup:Exception){detail=(detail+"; cleanup: "+(cleanup.message?:cleanup.javaClass.simpleName)).take(1024);disposition="CPU state uncertain; no automatic reconnect or resume"}
        val failed=snapshot.copy(phase=InitialInstallPhase.FAILED,cpuDisposition=disposition,message=detail)
        try{publish(failed)}catch(_:Exception){snapshot=failed.copy(journalFailure=true);observed(snapshot)}
        forgetMemory()
    }
    private fun forgetMemory(){original=null;material=null;qualified=null;candidate=null;reviewedResume=null}
}
