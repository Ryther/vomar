package org.openvimar.updater.core

data class ZigbeePairingCapabilities(val protocol:Int,val durationSeconds:Int,val forgetNetwork:Boolean) {
    init {require(protocol==1&&durationSeconds==120&&forgetNetwork){"Unsupported Zigbee pairing capability"}}
}
interface ZigbeePairingTransport {
    suspend fun pairingCapabilities():ZigbeePairingCapabilities
    suspend fun startZigbeePairing():ResetAck
}
/** Process-only, target-bound and single use; never reconstructed from reports. */
class ZigbeePairingReview internal constructor(val address:String,val identity:RuntimeIdentity):AutoCloseable {
    private var used=false
    @Synchronized internal fun consume(){check(!used){"Pairing review expired; inspect and review again"};used=true}
    @Synchronized override fun close(){used=true}
}
object ZigbeePairing {
    suspend fun inspect(transport:BleTransport,address:String,expectedUid:List<String>?=null):ZigbeePairingReview {
        try {
            transport.connect(address)
            val identity=RuntimeIdentityLookup.inspect(transport)
            require(expectedUid==null||identity.uid==expectedUid){"Selected device identity changed"}
            (transport as? ZigbeePairingTransport ?: error("Zigbee pairing is unavailable on this transport")).pairingCapabilities()
            return ZigbeePairingReview(address,identity.copy(uid=java.util.Collections.unmodifiableList(identity.uid.toList())))
        }finally{transport.close()}
    }
    suspend fun execute(review:ZigbeePairingReview,transport:BleTransport,beforeRequest:suspend()->Unit):ResetAck {
        review.consume()
        try {
            transport.connect(review.address)
            require(RuntimeIdentityLookup.inspect(transport)==review.identity){"Selected device identity changed"}
            val pairing=transport as? ZigbeePairingTransport ?: error("Zigbee pairing is unavailable on this transport")
            pairing.pairingCapabilities()
            // Persist uncertain mutation intent before a request can reach the device.
            beforeRequest()
            return pairing.startZigbeePairing()
        }finally{transport.close()}
    }
}
