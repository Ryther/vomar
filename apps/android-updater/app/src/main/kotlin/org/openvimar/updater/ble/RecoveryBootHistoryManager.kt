package org.openvimar.updater.ble

import no.nordicsemi.android.mcumgr.*
import no.nordicsemi.android.mcumgr.response.McuMgrResponse
import org.openvimar.updater.core.*

/** Exactly group 0x8041 READ command 0; no write/reset variant exists here. */
internal class RecoveryBootHistoryManager(transport:McuMgrTransport):McuManager(0x8041,transport) {
 fun read(callback:McuMgrCallback<RecoveryBootHistoryResponse>)=send(OP_READ,0,emptyMap<String,Any>(),RecoveryBootHistoryResponse::class.java,callback)
}
internal class RecoveryBootHistoryResponse:McuMgrResponse() {
 @JvmField var protocol:Long?=null
 @JvmField var record_size:Long?=null
 @JvmField var capacity:Long?=null
 @JvmField var current_image:Long?=null
 @JvmField var sequence:Long?=null
 @JvmField var pending_reason:Long?=null
 @JvmField var state:Map<String,Any>?=null
 @JvmField var entries:List<Map<String,Any>>?=null
 private fun original()=StrictSmpCbor.response(this,0x8041,1,allowSignedIntegers=true)
 fun validateWire() {
  val map=original()
  if("rc" in map){require(map.keys==setOf("rc")&&map["rc"] is Long&&(map["rc"] as Long) in 1L..65535L){"Malformed boot-history SMP return code"}}
  else if("err" in map){val error=map["err"] as? Map<*,*>
   require(map.keys==setOf("err")&&error!=null&&error.keys==setOf("group","rc")&&error.values.all{it is Long&&it in 0L..65535L}){"Malformed boot-history SMP error"}}
  else RecoveryBootHistoryCodec.fromMap(map)
 }
 fun rejection():Exception {
  validateWire();val map=original()
  val error=map["err"] as? Map<*,*>
  return if(map==mapOf("rc" to 8L)||(error?.get("group")==0L&&error["rc"]==8L))BootHistoryUnavailable()
   else IllegalStateException("Recovery boot-history diagnostic was refused. No device changes were requested.")
 }
 fun history():RecoveryBootHistory {validateWire();return RecoveryBootHistoryCodec.fromMap(original())}
}
