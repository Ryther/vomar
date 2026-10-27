package org.openvimar.updater.ble

import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.openvimar.updater.core.*

internal data class Slot(val image:Int,val slot:Int,val hash:String?,val active:Boolean,val bootable:Boolean,val version:String?=null)
internal data class Chunk(val offset:Int,val match:Boolean?)
/** Narrow platform seam: a chunk is one low-level SMP request, never a managed transfer. */
internal interface BleGateway {
 suspend fun connect(address:String)
 fun checkReady()
 suspend fun identity():RuntimeIdentity = error("Runtime identity command unavailable")
 suspend fun identityV2():RuntimeIdentity = error("Typed runtime identity command unavailable")
 suspend fun bootHistory():RecoveryBootHistory = throw BootHistoryUnavailable()
 suspend fun images():List<Slot>
 suspend fun chunk(data:ByteArray,offset:Int,image:Int):Chunk
 suspend fun reset()
 suspend fun bootMigration(hash:String):ResetAck=error("Purpose-specific migration boot gateway unavailable")
 suspend fun pairingCapabilities():ZigbeePairingCapabilities=error("Zigbee pairing unavailable on this recovery")
 suspend fun startZigbeePairing():ResetAck=error("Zigbee pairing unavailable on this recovery")
 fun close()
}
class NordicBleTransport internal constructor(private val expectedAddress:String,private val gateway:BleGateway):BleTransport,MigrationBootTransport,BootHistoryTransport,ZigbeePairingTransport {
 constructor(context:android.content.Context,address:String):this(address,AndroidBleGateway(context,address))
 private val command=Mutex()
 private suspend fun <T> serial(block:suspend()->T):T=command.withLock {
  try {block()} catch(e:CancellationException){gateway.close();throw e}
 }
 override suspend fun connect(address:String)=serial {check(address.equals(expectedAddress,true)){"Unexpected BLE address"};gateway.connect(expectedAddress);gateway.checkReady()}
 override suspend fun identity():RuntimeIdentity=serial {gateway.checkReady();gateway.identity()}
 override suspend fun identityV2():RuntimeIdentity=serial {gateway.checkReady();gateway.identityV2()}
 override suspend fun bootHistory():RecoveryBootHistory=serial {gateway.checkReady();gateway.bootHistory()}
 override suspend fun pairingCapabilities():ZigbeePairingCapabilities=serial {gateway.checkReady();gateway.pairingCapabilities()}
 override suspend fun startZigbeePairing():ResetAck=serial {
  gateway.checkReady()
  try{gateway.startZigbeePairing()}catch(_:TransportDisconnected){ResetAck.LOST}catch(_:ResetResponseLost){ResetAck.LOST}
 }
 override suspend fun images():RemoteImages=serial {
  gateway.checkReady()
  val rows=gateway.images();check(rows.all{it.image==0 && it.slot in 0..1}){"Foreign image/slot"}
  check(rows.map{it.slot}.distinct().size==rows.size){"Duplicate image slot"}
  val recovery=rows.singleOrNull{it.slot==1} ?: error("Missing recovery slot1")
  check(recovery.active && recovery.bootable && recovery.hash!=null){"Recovery must be active and bootable"}
  fun Slot.remote()=RemoteImage(hash,active,bootable,version)
  RemoteImages(rows.singleOrNull{it.slot==0}?.remote(),recovery.remote())
 }
 override suspend fun upload(data:ByteArray,onAck:suspend(Int)->Unit)=serial {
  check(data.isNotEmpty()){"Empty image"}
  var offset=0;var negotiated=false;var stalled=0
  do {
   gateway.checkReady()
   val response=gateway.chunk(data,offset,0)
   check(response.match!=false){"Device reports full-file hash mismatch"}
   val next=response.offset
   check(next in 0..data.size){"Device offset outside file"}
   check(!negotiated || next>=offset){"Device offset moved backward"}
   stalled=if(next==offset) stalled+1 else 0
   check(stalled<3){"Three ACKs without progress"}
   onAck(next) // persistence must complete before any further BLE request
   delay(50)
   offset=next;negotiated=true
  } while(offset<data.size)
 }
 override suspend fun reset():ResetAck=serial {
  gateway.checkReady()
  try {gateway.reset();ResetAck.ACKNOWLEDGED} catch(_:TransportDisconnected){ResetAck.LOST} catch(_:ResetResponseLost){ResetAck.LOST}
 }
 override suspend fun bootMigration(expectedHash:String):ResetAck=serial {
  gateway.checkReady()
  try {gateway.bootMigration(expectedHash)}catch(_:TransportDisconnected){ResetAck.LOST}catch(_:ResetResponseLost){ResetAck.LOST}
 }
 override suspend fun close(){gateway.close()}
}
internal class ResetResponseLost:Exception("Reset response timed out")
