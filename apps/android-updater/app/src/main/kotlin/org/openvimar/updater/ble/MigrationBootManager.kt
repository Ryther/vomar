package org.openvimar.updater.ble

import no.nordicsemi.android.mcumgr.*
import no.nordicsemi.android.mcumgr.response.McuMgrResponse
import org.openvimar.updater.core.*

/** Authenticated project group0x8042 WRITE0; no ordinary-reset alias. */
internal class MigrationBootManager(transport:McuMgrTransport):McuManager(0x8042,transport) {
    fun boot(hash:String,callback:McuMgrCallback<MigrationBootResponse>) {
        require(Regex("[0-9a-f]{64}").matches(hash))
        val bytes=ByteArray(32){index->hash.substring(index*2,index*2+2).toInt(16).toByte()}
        send(OP_WRITE,0,mapOf("hash" to bytes),MigrationBootResponse::class.java,callback)
    }
}
internal class MigrationBootResponse:McuMgrResponse() {
    @JvmField var accepted:Boolean?=null
    fun acknowledgement():ResetAck {
        val map=StrictSmpCbor.response(this,0x8042,3)
        require(map.keys==setOf("accepted")&&map["accepted"]===true){"Migration boot was refused or its response was malformed"}
        return ResetAck.ACKNOWLEDGED
    }
    fun rejection():Exception {
        val map=StrictSmpCbor.response(this,0x8042,3)
        if("rc" in map)require(map["rc"] is Long){"SMP return code must be an unsigned integer"}
        return if(map.keys==setOf("rc")&&map["rc"]==8L)MigrationBootCommandUnavailable()
            else IllegalStateException("Migration boot request rejected or unsupported response shape")
    }
    fun validateWire(){StrictSmpCbor.response(this,0x8042,3)}
}
