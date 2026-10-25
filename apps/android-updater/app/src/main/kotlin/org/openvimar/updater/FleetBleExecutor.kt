package org.openvimar.updater

import kotlinx.coroutines.*
import org.openvimar.updater.core.*

/** Actual common BLE engine; metadata names/addresses never replace runtime UID. */
internal class FleetBleExecutor(private val releaseLoader:suspend(FleetReleaseRef)->ValidatedCommonPackage,
    private val transportFactory:(String)->BleTransport,private val store:SessionStore,
    private val checkSubmission:()->Unit={}) : FleetJobExecutor {
    override suspend fun execute(context:FleetExecutionContext,emit:suspend(FleetExecutionEvent)->Unit):FleetExecutionResult {
        val record=context.job.device
        if(!context.job.nearbyReady||record.address==null||record.uid.size!=2)
            return FleetExecutionResult(FleetJobState.BLOCKED,"Confirm nearby readiness and verify this dimmer's UID before an automatic group update")
        var pkg:ValidatedPackage?=null
        var transport:BleTransport?=null
        var coordinatorOwnsClose=false
        try {
            currentCoroutineContext().ensureActive();checkSubmission()
            val common=releaseLoader(context.release)
            require(common.bundleDigest==context.release.digest&&common.manifest.main.signedRegionSha256==context.release.mainHash&&common.manifest.main.version==context.release.version){"Immutable release reference changed"}
            val native=transportFactory(record.address);transport=native
            val coroutine=currentCoroutineContext()
            fun check(){coroutine.ensureActive();checkSubmission()}
            val guarded=object:BleTransport,MigrationBootTransport {
                override suspend fun connect(address:String){check();native.connect(address);check()}
                override suspend fun identity():RuntimeIdentity {check();return native.identity().also{check()}}
                override suspend fun identityV2():RuntimeIdentity {check();return native.identityV2().also{check()}}
                override suspend fun images():RemoteImages {check();return native.images().also{check()}}
                override suspend fun upload(data:ByteArray,onAck:suspend(Int)->Unit){check();native.upload(data){check();onAck(it)}}
                override suspend fun reset():ResetAck{check();return native.reset().also{check()}}
                override suspend fun bootMigration(expectedHash:String):ResetAck{check();return (native as? MigrationBootTransport ?: error("Migration boot transport unavailable")).bootMigration(expectedHash).also{check()}}
                override suspend fun close()=native.close()
            }
            guarded.connect(record.address)
            val identity=try{RuntimeIdentityLookup.forRelease(guarded,common.manifest)}catch(_:IdentityCommandUnavailable){
                return FleetExecutionResult(FleetJobState.BLOCKED,"Legacy recovery cannot prove this planned UID. Prepare this dimmer manually before using a group.")
            }
            require(identity.uid==record.uid){"Connected runtime UID differs from this planned dimmer"}
            pkg=common.bind(identity,record.address)
            val previous=store.load(pkg.bundleDigest,record.address,pkg.targetUid)
            require(previous==null||UpdatePlanner.matches(pkg,previous)){"Checkpoint identity mismatch"}
            if(previous!=null&&SessionEvidence.from(previous).needsResetConfirmation)
                return FleetExecutionResult(FleetJobState.UNCERTAIN_RESET,"A reset may have been sent. Open this exact device's session and review an explicit reset retry.")
            var last=FleetExecutionResult(FleetJobState.PAUSED,"Coordinator ended without verified completion")
            coordinatorOwnsClose=true
            UpdateCoordinator().run(pkg,guarded,store,allowResetRetry=false){event->
                when(event) {
                    is UpdateEvent.Progress->emit(FleetExecutionEvent((event.acknowledgedOffset*100L/event.total).toInt(),"Uploading ${event.phase}: ${event.acknowledgedOffset}/${event.total} bytes acknowledged"))
                    is UpdateEvent.AwaitingOperator->{last=FleetExecutionResult(if(event.resetAcknowledged)FleetJobState.AWAITING_RETURN else FleetJobState.UNCERTAIN_RESET,
                        if(event.resetAcknowledged)"Firmware images verified and reset acknowledged; online return remains unobserved" else "Firmware images verified; reset acknowledgement missing. Review this device before retrying.")}
                    is UpdateEvent.Paused->last=FleetExecutionResult(FleetJobState.PAUSED,event.reason)
                    is UpdateEvent.Planned->emit(FleetExecutionEvent(message="Runtime update plan: ${event.decision}"))
                    is UpdateEvent.Reconnecting->emit(FleetExecutionEvent(message="Reconnecting after transport loss (${event.attempt})"))
                    UpdateEvent.Stopped->last=FleetExecutionResult(FleetJobState.PAUSED,"Stopped; checkpoint preserved")
                }
            }
            return last
        } catch(cancelled:CancellationException) {
            val checkpoint=withContext(NonCancellable){pkg?.let{store.load(it.bundleDigest,record.address,it.targetUid)}}
            return FleetExecutionResult(if(SessionEvidence.from(checkpoint).needsResetConfirmation)FleetJobState.UNCERTAIN_RESET else FleetJobState.PAUSED,
                "Stopped; firmware checkpoint preserved. An uncertain reset requires explicit device review.")
        } catch(error:Exception) {
            return FleetExecutionResult(FleetJobState.BLOCKED,error.message ?: "Runtime compatibility check failed")
        } finally {if(!coordinatorOwnsClose)withContext(NonCancellable){runCatching{transport?.close()}}}
    }
}
