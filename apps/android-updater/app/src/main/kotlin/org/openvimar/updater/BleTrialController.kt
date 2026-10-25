package org.openvimar.updater

import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.openvimar.updater.core.*

/** Display metadata only: no firmware bytes, runtime grants or restorable approval. */
data class BleTrialReviewInfo(val id:String,val address:String,val digest:String,val version:String,
    val currentVersion:String?,val identitySummary:String,val legacy:Boolean,val resumable:Boolean,val resetRetryRequired:Boolean)
/** Process-only presentation. Never accepted as an execution grant or restored from a report. */
data class BleTrialTargetInfo(val address:String,val identitySummary:String?=null,val currentVersion:String?=null,val version:String?=null)
enum class BleTrialPhase(val label:String) {
    IDLE("Ready to inspect"), INSPECTING("Inspecting dimmer"), REVIEW("Ready for review"),
    PREPARING("Preparing update"), TRANSFERRING("Transferring firmware"), VERIFYING("Verifying firmware"),
    RESTARTING("Restarting dimmer"), RECONNECTING("Reconnecting"), AWAITING_RETURN("Waiting for Zigbee"), PAUSED("Paused")
}
data class BleTrialState(val status:String="Choose a signed candidate and inspect one Bluetooth dimmer.",
    val busy:Boolean=false,val progressPercent:Int?=null,val review:BleTrialReviewInfo?=null,val acknowledged:Boolean?=null,
    val target:BleTrialTargetInfo?=null,val phase:BleTrialPhase=BleTrialPhase.IDLE)

/** The service owns coroutine lifetime. This owner never starts or restores an operation itself. */
class BleTrialController(private val candidateLoader:suspend()->BleTrialCandidate,
    private val transportFactory:(String,()->Unit)->BleTransport,private val bootstrap:BootstrapStore,
    private val sessions:SessionStore,private val lease:suspend(suspend(()->Unit)->Unit)->Unit,
    // The second argument is the Bluetooth target address, never status text.
    private val reportWriter:suspend(BleTrialState,String)->Unit={_,_->}) {
    private val mutableState=MutableStateFlow(BleTrialState())
    val state=mutableState.asStateFlow()
    private val lock=Any()
    private data class Held(val candidate:BleTrialCandidate,val review:BleTrialReview,val info:BleTrialReviewInfo)
    private var held:Held?=null

    private fun admit(status:String,phase:BleTrialPhase,inspectionAddress:String?=null):Held?=synchronized(lock){
        check(!mutableState.value.busy){"Another Bluetooth trial operation is active"}
        val previous=held;held=null
        // Display retention is independent of consuming the single-use review above.
        val target=inspectionAddress?.let{BleTrialTargetInfo(it)} ?: mutableState.value.target
        mutableState.value=BleTrialState(status=status,busy=true,target=target,phase=phase)
        previous
    }
    private fun update(change:(BleTrialState)->BleTrialState)=synchronized(lock){mutableState.value=change(mutableState.value)}
    private fun revoke(){synchronized(lock){held?.review?.close();held=null;mutableState.value=mutableState.value.copy(review=null)}}
    private suspend fun finish(address:String){
        // Do not release admission until the final immutable report has drained.
        // A report never grants authority, including when Android restores it.
        withContext(NonCancellable){
            val snapshot=synchronized(lock){mutableState.value.copy(busy=false)}
            try{reportWriter(snapshot,address)}catch(failure:Exception){
                revoke()
                update{it.copy(phase=BleTrialPhase.PAUSED,status="${it.status} Trial report could not be saved: ${failure.message ?: "storage unavailable"}")}
            }
            update{it.copy(busy=false)}
        }
    }

    suspend fun inspect(address:String){
        admit("Checking the signed candidate and selected Bluetooth dimmer. No firmware will be installed.",
            BleTrialPhase.INSPECTING,address)?.review?.close()
        var pending:BleTrialReview?=null
        try{
            lease{check->
                check()
                val candidate=candidateLoader();check()
                val review=candidate.review(address,transportFactory(address,check),bootstrap,sessions)
                pending=review;check()
                val info=BleTrialReviewInfo(UUID.randomUUID().toString(),review.address,review.digest,review.version,
                    review.currentVersion,review.identitySummary,review.legacy,review.resumable,review.resetRetryRequired)
                synchronized(lock){
                    held=Held(candidate,review,info)
                    mutableState.value=mutableState.value.copy(review=info,
                        target=BleTrialTargetInfo(info.address,info.identitySummary,info.currentVersion,info.version),
                        phase=BleTrialPhase.REVIEW,status=
                        if(review.resetRetryRequired)"Saved progress includes an uncertain restart. Review this dimmer and explicitly confirm any restart retry."
                        else "Signed candidate and selected dimmer checked. Review the target before starting this one Bluetooth trial.")
                }
                pending=null
            }
        }catch(cancelled:CancellationException){
            revoke();update{it.copy(phase=BleTrialPhase.PAUSED,status="Bluetooth trial inspection stopped. Inspect this dimmer again before starting.")};throw cancelled
        }catch(failure:Exception){
            revoke();update{it.copy(phase=BleTrialPhase.PAUSED,status="Inspection paused: ${failure.message ?: "Bluetooth inspection failed"}")}
        }finally{pending?.close();finish(address)}
    }

    suspend fun execute(reviewId:String,confirmResetRetry:Boolean=false){
        val selected=admit("Checking the reviewed candidate and dimmer before starting the Bluetooth trial.",BleTrialPhase.PREPARING)
        try{
            require(selected!=null&&selected.info.id==reviewId){"Review expired. Inspect and review this dimmer again"}
            require(!selected.info.resetRetryRequired||confirmResetRetry){"Explicit confirmation is required before retrying this uncertain restart"}
            require(!confirmResetRetry||selected.info.resetRetryRequired){"This review does not authorize a restart retry"}
            lease{check->
                check()
                val revalidated=candidateLoader();check()
                require(revalidated.digest==selected.info.digest){"Selected candidate changed. Inspect and review this dimmer again"}
                // The original instance owns the review; revalidation never transfers its grant.
                selected.candidate.run(selected.review,{address->check();transportFactory(address,check)},bootstrap,sessions,
                    allowResetRetry=confirmResetRetry){event->check();present(event)}
                check()
                if(mutableState.value.acknowledged==null&&!mutableState.value.status.startsWith("Trial paused:")){
                    update{it.copy(phase=BleTrialPhase.PAUSED,status="Trial paused. Inspect the dimmer and saved progress before continuing.")}
                }
            }
        }catch(cancelled:CancellationException){
            update{it.copy(phase=BleTrialPhase.PAUSED,status="Bluetooth trial stopped. Saved progress remains available; inspect and review again before resuming.")};throw cancelled
        }catch(failure:Exception){
            update{it.copy(phase=BleTrialPhase.PAUSED,status="Trial paused: ${failure.message ?: "Bluetooth trial could not continue"}")}
        }finally{selected?.review?.close();revoke();finish(selected?.info?.address.orEmpty())}
    }

    private fun present(event:UpdateEvent){
        update{previous->when(event){
            is UpdateEvent.Progress->previous.copy(progressPercent=(event.acknowledgedOffset*100L/event.total).toInt().coerceIn(0,100),
                phase=if(event.acknowledgedOffset==event.total)BleTrialPhase.VERIFYING else BleTrialPhase.TRANSFERRING,
                status=if(event.acknowledgedOffset==event.total)"Upload acknowledged. Checking the firmware image on this dimmer."
                    else "Uploading firmware: ${event.acknowledgedOffset} of ${event.total} bytes acknowledged.")
            is UpdateEvent.Planned->previous.copy(progressPercent=null,phase=when(event.decision){
                Decision.UploadMigration,Decision.UploadMain->BleTrialPhase.PREPARING
                Decision.RunMigration,Decision.ReturnToMain->BleTrialPhase.RESTARTING
                Decision.AwaitOperator->BleTrialPhase.VERIFYING
                Decision.Reject->BleTrialPhase.PAUSED
            },status=when(event.decision){
                Decision.UploadMigration->"Preparing independent Bluetooth recovery."
                Decision.RunMigration->"Requesting the signed recovery preparation restart."
                Decision.UploadMain->"Installing the reviewed candidate firmware."
                Decision.ReturnToMain->"Firmware image verified. Requesting application restart."
                Decision.AwaitOperator->"Checking the recorded restart result."
                Decision.Reject->"Trial paused: installed firmware is incompatible."
            })
            is UpdateEvent.Reconnecting->previous.copy(progressPercent=null,phase=BleTrialPhase.RECONNECTING,status="Bluetooth disconnected. Reconnecting (${event.attempt}).")
            is UpdateEvent.Paused->previous.copy(progressPercent=null,phase=BleTrialPhase.PAUSED,status="Trial paused: ${event.reason}")
            is UpdateEvent.AwaitingOperator->previous.copy(progressPercent=null,acknowledged=event.resetAcknowledged,
                phase=if(event.resetAcknowledged)BleTrialPhase.AWAITING_RETURN else BleTrialPhase.PAUSED,status=
                if(event.resetAcknowledged)"Firmware image verified and reset acknowledged. Check that this dimmer returns on Zigbee."
                else "Firmware image verified; reset acknowledgement is uncertain. Inspect this dimmer before any explicit restart retry.")
            UpdateEvent.Stopped->previous.copy(progressPercent=null,phase=BleTrialPhase.PAUSED,status="Trial paused: operation stopped. Inspect and review again before resuming.")
        }}
    }

    fun invalidate():Boolean=synchronized(lock){
        if(mutableState.value.busy)return@synchronized false
        held?.review?.close();held=null
        mutableState.value=BleTrialState(status="Review cleared. Inspect the selected Bluetooth dimmer before starting a trial.")
        true
    }
}
