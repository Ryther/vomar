package org.openvimar.updater

internal enum class FirmwareKind { UNKNOWN, STOCK, CUSTOM }
internal enum class FleetRoute { BLE, ZIGBEE }
internal enum class FleetMode { SEQUENTIAL, NETWORK_PARALLEL }
internal enum class FleetJobState { QUEUED, WAITING_NEARBY, RUNNING, PAUSED, UNCERTAIN_RESET, AWAITING_RETURN, VERIFIED, BLOCKED, FAILED, CANCELLED }
internal data class ZigbeeOtaReference(val manufacturerCode:Int,val imageType:Int,val fileVersion:Long,
    val sha256:String,val size:Long,val model:String,val profile:Int,val source:String)
/** Immutable organisation reference. Executors independently revalidate bytes/signatures. */
internal data class FleetReleaseRef(val digest:String,val version:String,val mainHash:String,val cachePath:String,
    val schemaVersion:Int=2,val zigbeeOta:ZigbeeOtaReference?=null,val targetRecoveryHash:String?=null)
/** Project metadata is availability information, never package or operation admission. */
internal sealed interface FleetReleaseLookup {
    data class Downloaded(val firmware:FleetReleaseRef):FleetReleaseLookup
    data class Experimental(val distributionVersion:String,val firmwareVersion:String,val releasePage:String):FleetReleaseLookup
}
internal data class FleetJob(val id:String,val device:DeviceRecord,val route:FleetRoute,
    val state:FleetJobState=FleetJobState.QUEUED,val nearbyReady:Boolean=false,val progress:Int?=null,
    val message:String="Queued",val resumeRequested:Boolean=false,val remoteSubmissionMayHaveStarted:Boolean=false)
internal data class FleetGroup(val id:String,val release:FleetReleaseRef,val jobs:List<FleetJob>,val mode:FleetMode,
    val createdAt:Long,val paused:Boolean=true,val cancelled:Boolean=false)
internal data class FleetExecutionContext(val groupId:String,val job:FleetJob,val release:FleetReleaseRef)
internal data class FleetExecutionEvent(val progress:Int?=null,val message:String,val submissionMayHaveStarted:Boolean=false)
internal data class FleetExecutionResult(val state:FleetJobState,val message:String)
internal fun interface FleetJobExecutor {
    suspend fun execute(context:FleetExecutionContext,emit:suspend(FleetExecutionEvent)->Unit):FleetExecutionResult
}
internal fun interface FleetJobReconciler {
    /** Read-only backend evidence: VERIFIED target return, PAUSED proven idle,
     * or UNCERTAIN_RESET. Never issues/resubmits an update command. */
    suspend fun reconcile(context:FleetExecutionContext):FleetExecutionResult
}
internal interface FleetQueuePersistence {
    fun load():List<FleetGroup>
    /** Durable before any new submission. Failures must propagate. */
    fun save(groups:List<FleetGroup>)
}
