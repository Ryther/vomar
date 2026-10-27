package org.openvimar.updater.ble

import no.nordicsemi.android.mcumgr.McuMgrCallback
import no.nordicsemi.android.mcumgr.McuMgrScheme
import no.nordicsemi.android.mcumgr.McuMgrTransport
import no.nordicsemi.android.mcumgr.exception.McuMgrException
import no.nordicsemi.android.mcumgr.response.McuMgrResponse
import no.nordicsemi.android.mcumgr.util.CBOR
import org.junit.Assert.*
import org.junit.Test
import org.openvimar.updater.core.ResetAck
import org.openvimar.updater.core.ZigbeePairingCapabilities

class ZigbeePairingManagerTest {
    private val capabilities=mapOf<String,Any>("protocol" to 1,"duration" to 120,"forget" to true)
    private fun <T:McuMgrResponse> wire(payload:ByteArray,type:Class<T>,operation:Int,
        group:Int=0x8043,command:Int=0,flags:Int=0,version:Int=1):T {
        val header=byteArrayOf(((version shl 3) or operation).toByte(),flags.toByte(),
            (payload.size shr 8).toByte(),payload.size.toByte(),(group shr 8).toByte(),group.toByte(),0,command.toByte())
        return McuMgrResponse.buildResponse(McuMgrScheme.BLE,header+payload,type)
    }
    private fun read(map:Map<String,Any>)=wire(CBOR.toBytes(map),ZigbeePairingReadResponse::class.java,1)
    private fun write(map:Map<String,Any>)=wire(CBOR.toBytes(map),ZigbeePairingWriteResponse::class.java,3)
    private fun <T:McuMgrResponse> callback()=object:McuMgrCallback<T> {
        override fun onResponse(response:T){}
        override fun onError(error:McuMgrException){throw AssertionError("Unexpected transport failure",error)}
    }

    @Test fun discoveryAndMutationHaveDistinctExactAuthenticatedWireRequests() {
        val packets=mutableListOf<ByteArray>()
        val types=mutableListOf<Class<*>>()
        val transport=object:McuMgrTransport {
            override fun getScheme()=McuMgrScheme.BLE
            override fun <T:McuMgrResponse> send(bytes:ByteArray,timeout:Long,type:Class<T>):T=error("No synchronous send")
            override fun <T:McuMgrResponse> send(bytes:ByteArray,timeout:Long,type:Class<T>,callback:McuMgrCallback<T>){packets+=bytes;types+=type}
            override fun connect(callback:McuMgrTransport.ConnectionCallback?)=error("Manager must use the admitted transport")
            override fun changeMode(name:String,callback:McuMgrTransport.ModeChangeCallback?):Boolean=error("No implicit mode change")
            override fun release(){}
            override fun addObserver(observer:McuMgrTransport.ConnectionObserver){}
            override fun removeObserver(observer:McuMgrTransport.ConnectionObserver){}
        }
        val manager=ZigbeePairingManager(transport)
        manager.read(callback())
        assertEquals("Discovery must not submit a pairing write",1,packets.size)
        assertEquals(0,packets.single()[0].toInt() and 7)
        assertEquals(emptyMap<String,Any>(),StrictSmpCbor.decode(packets.single().copyOfRange(8,packets.single().size)))
        manager.start(callback())
        assertEquals(2,packets.size)
        assertEquals(2,packets[1][0].toInt() and 7)
        assertEquals(mapOf("duration" to 120L,"forget" to true),StrictSmpCbor.decode(packets[1].copyOfRange(8,packets[1].size)))
        assertEquals(listOf(ZigbeePairingReadResponse::class.java,ZigbeePairingWriteResponse::class.java),types)
        for(packet in packets){
            assertEquals(1,(packet[0].toInt() shr 3) and 3)
            assertEquals(0,packet[1].toInt())
            assertEquals(packet.size-8,((packet[2].toInt() and 255) shl 8) or (packet[3].toInt() and 255))
            assertEquals(0x80,packet[4].toInt() and 255);assertEquals(0x43,packet[5].toInt() and 255)
            assertEquals(0,packet[7].toInt())
        }
    }
    @Test fun actualNordicResponsesRequireTheExactCapabilityAndExplicitAcknowledgment() {
        val discovery=read(capabilities);discovery.validateWire()
        assertEquals(ZigbeePairingCapabilities(1,120,true),discovery.capabilities())
        val mutation=write(mapOf("accepted" to true));mutation.validateWire()
        assertEquals(ResetAck.ACKNOWLEDGED,mutation.acknowledgement())
    }
    @Test fun unsupportedCapabilityValuesAndMissingOrExtraFieldsCannotEnablePairing() {
        val unsupported=listOf(
            capabilities+("protocol" to 2),capabilities+("duration" to 119),capabilities+("duration" to 121),
            capabilities+("forget" to false),capabilities-"protocol",capabilities-"duration",capabilities-"forget",
            capabilities+("rc" to 0),capabilities+("unexpected" to true),emptyMap(),mapOf("rc" to 8),
            mapOf("err" to mapOf("group" to 0x8043,"rc" to 1)))
        for(map in unsupported)assertThrows("Must refuse capability response $map",Exception::class.java){read(map).capabilities()}
    }
    @Test fun nordicScalarCoercionCannotPromoteMalformedCapabilitiesOrAcceptance() {
        for((field,values) in mapOf(
            "protocol" to listOf<Any>("1",1.0,true),
            "duration" to listOf<Any>("120",120.0,true),
            "forget" to listOf<Any>("true",1,1.0))){
            for(value in values)assertThrows("Must reject $field=$value",Exception::class.java){read(capabilities+(field to value)).capabilities()}
        }
        for(value in listOf<Any>("true",1,1.0)){
            assertThrows("Must require a CBOR boolean acknowledgment",Exception::class.java){write(mapOf("accepted" to value)).acknowledgement()}
        }
    }
    @Test fun refusalMissingAcceptanceOrAdditionalStatusNeverAcknowledgesMutation() {
        for(map in listOf(emptyMap(),mapOf("accepted" to false),mapOf("rc" to 0),mapOf("rc" to 8),
            mapOf("accepted" to true,"rc" to 0),mapOf("accepted" to true,"unexpected" to true),
            mapOf("accepted" to true,"err" to mapOf("group" to 0x8043,"rc" to 1)))){
            assertThrows("Must not acknowledge $map",Exception::class.java){write(map).acknowledgement()}
        }
    }
    @Test fun foreignGroupCommandOperationOrFlagsCannotAuthorizeDiscoveryOrMutation() {
        val discovery=CBOR.toBytes(capabilities)
        val mutation=CBOR.toBytes(mapOf("accepted" to true))
        val invalidRead=listOf(
            {wire(discovery,ZigbeePairingReadResponse::class.java,1,group=0x8042)},
            {wire(discovery,ZigbeePairingReadResponse::class.java,1,command=1)},
            {wire(discovery,ZigbeePairingReadResponse::class.java,3)},
            {wire(discovery,ZigbeePairingReadResponse::class.java,1,flags=1)})
        for(response in invalidRead)assertThrows(Exception::class.java){response().capabilities()}
        val invalidWrite=listOf(
            {wire(mutation,ZigbeePairingWriteResponse::class.java,3,group=0x8042)},
            {wire(mutation,ZigbeePairingWriteResponse::class.java,3,command=1)},
            {wire(mutation,ZigbeePairingWriteResponse::class.java,1)},
            {wire(mutation,ZigbeePairingWriteResponse::class.java,3,flags=1)})
        for(response in invalidWrite)assertThrows(Exception::class.java){response().acknowledgement()}
    }
    @Test fun duplicateKeysAndTrailingCborCannotGrantCapabilityOrAcknowledgment() {
        val repeatedCapability=byteArrayOf(0xa4.toByte())+CBOR.toBytes("protocol")+byteArrayOf(1)+CBOR.toBytes("duration")+byteArrayOf(0x18,0x78)+CBOR.toBytes("forget")+byteArrayOf(0xf5.toByte())+CBOR.toBytes("protocol")+byteArrayOf(1)
        val repeatedAcceptance=byteArrayOf(0xa2.toByte())+CBOR.toBytes("accepted")+byteArrayOf(0xf5.toByte())+CBOR.toBytes("accepted")+byteArrayOf(0xf5.toByte())
        for(payload in listOf(repeatedCapability,CBOR.toBytes(capabilities)+byteArrayOf(0))){
            assertThrows(Exception::class.java){wire(payload,ZigbeePairingReadResponse::class.java,1).capabilities()}
        }
        for(payload in listOf(repeatedAcceptance,CBOR.toBytes(mapOf("accepted" to true))+byteArrayOf(0))){
            assertThrows(Exception::class.java){wire(payload,ZigbeePairingWriteResponse::class.java,3).acknowledgement()}
        }
    }
    @Test fun malformedStatusAndMissingOriginalWireEvidenceCannotGrantPairing() {
        for(value in listOf<Any>("8",8.5,true)){
            val bytes=CBOR.toBytes(mapOf("rc" to value))
            assertThrows(Exception::class.java){wire(bytes,ZigbeePairingReadResponse::class.java,1).capabilities()}
            assertThrows(Exception::class.java){wire(bytes,ZigbeePairingWriteResponse::class.java,3).acknowledgement()}
        }
        assertThrows(IllegalArgumentException::class.java){ZigbeePairingReadResponse().validateWire()}
        assertThrows(IllegalArgumentException::class.java){ZigbeePairingWriteResponse().validateWire()}
    }
}
