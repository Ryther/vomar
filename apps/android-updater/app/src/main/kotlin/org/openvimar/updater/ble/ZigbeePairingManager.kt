package org.openvimar.updater.ble

import no.nordicsemi.android.mcumgr.*
import no.nordicsemi.android.mcumgr.response.McuMgrResponse
import org.openvimar.updater.core.*

/** Authenticated group0x8043: capability discovery never requests a transition. */
internal class ZigbeePairingManager(transport:McuMgrTransport):McuManager(0x8043,transport) {
    fun read(callback:McuMgrCallback<ZigbeePairingReadResponse>)=
        send(OP_READ,0,emptyMap<String,Any>(),ZigbeePairingReadResponse::class.java,callback)
    fun start(callback:McuMgrCallback<ZigbeePairingWriteResponse>)=
        send(OP_WRITE,0,mapOf("duration" to 120,"forget" to true),ZigbeePairingWriteResponse::class.java,callback)
}
internal class ZigbeePairingReadResponse:McuMgrResponse() {
    @JvmField var protocol:Long?=null
    @JvmField var duration:Long?=null
    @JvmField var forget:Boolean?=null
    fun capabilities():ZigbeePairingCapabilities {
        val map=StrictSmpCbor.response(this,0x8043,1)
        require(map.keys==setOf("protocol","duration","forget")&&map["protocol"]==1L&&map["duration"]==120L&&map["forget"]==true){"Zigbee pairing unavailable or unsupported by this recovery"}
        return ZigbeePairingCapabilities(1,120,true)
    }
    fun validateWire(){StrictSmpCbor.response(this,0x8043,1)}
}
internal class ZigbeePairingWriteResponse:McuMgrResponse() {
    @JvmField var accepted:Boolean?=null
    fun acknowledgement():ResetAck {
        val map=StrictSmpCbor.response(this,0x8043,3)
        require(map.keys==setOf("accepted")&&map["accepted"]==true){"Zigbee pairing refused or malformed acknowledgment"}
        return ResetAck.ACKNOWLEDGED
    }
    fun validateWire(){StrictSmpCbor.response(this,0x8043,3)}
}
