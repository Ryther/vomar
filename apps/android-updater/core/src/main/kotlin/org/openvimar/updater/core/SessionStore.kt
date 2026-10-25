package org.openvimar.updater.core

import kotlinx.serialization.Serializable

@Serializable enum class Phase { UPLOAD_MIGRATION, MIGRATION_RESET_INTENT, UPLOAD_MAIN, FINAL_RESET_INTENT, AWAIT_OPERATOR }
@Serializable data class Checkpoint(
    val schemaVersion:Int=1, val bundleDigest:String, val bleAddress:String,
    val phase:Phase, val ackOffset:Int=0, val resetAcknowledged:Boolean=false,val targetUid:List<String>?=null,val runtimeIdentity:RuntimeIdentity?=null
)
/** Implementations must atomically replace a complete record; corrupt/unsupported records must throw. */
interface SessionStore {
    suspend fun load(bundleDigest:String, address:String):Checkpoint?
    suspend fun load(bundleDigest:String,address:String,targetUid:List<String>?):Checkpoint? = load(bundleDigest,address)
    suspend fun save(checkpoint:Checkpoint)
}
@Serializable data class RemoteImage(val hash:String?,val active:Boolean,val bootable:Boolean,val version:String?=null)
/** Adapter must reject duplicate/foreign image indices and map image0 slot0/slot1 exactly. */
@Serializable data class RemoteImages(val primary:RemoteImage?,val recovery:RemoteImage)
enum class ResetAck { ACKNOWLEDGED, LOST }
interface BleTransport {
    /** Must verify exact address, SMP service and authenticated bonding on every connection. */
    suspend fun connect(address:String)
    suspend fun identity():RuntimeIdentity = throw IdentityCommandUnavailable()
    suspend fun identityV2():RuntimeIdentity = error("Typed identity query is not implemented by this transport")
    suspend fun images():RemoteImages
    /** ACK offsets are remote-authoritative. Start/resume negotiation belongs to transport. */
    suspend fun upload(data:ByteArray,onAck:suspend (Int)->Unit)
    suspend fun reset():ResetAck
    /** Release this session's owned transport resources; never reset global Bluetooth. */
    suspend fun close()
}
/** Only this classified failure authorizes reconnect; other failures pause immediately. */
class TransportDisconnected(message:String="Disconnected"):Exception(message)
sealed interface UpdateEvent {
    data class Planned(val decision:Decision):UpdateEvent
    data class Progress(val phase:Phase,val acknowledgedOffset:Int,val total:Int):UpdateEvent
    data class Reconnecting(val attempt:Int,val delayMillis:Long):UpdateEvent
    data class Paused(val reason:String):UpdateEvent
    data class AwaitingOperator(val resetAcknowledged:Boolean):UpdateEvent
    data object Stopped:UpdateEvent
}
