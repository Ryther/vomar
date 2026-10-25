package org.openvimar.updater.ble

import io.runtime.mcumgr.McuMgrScheme
import io.runtime.mcumgr.McuMgrTransport
import io.runtime.mcumgr.McuMgrCallback
import io.runtime.mcumgr.response.McuMgrResponse
import io.runtime.mcumgr.util.CBOR
import org.junit.Assert.*
import org.junit.Test
import org.openvimar.updater.core.LoaderContract

class RuntimeIdentityV2Test {
    private fun wire(map:Map<String,Any>,command:Int=1):RuntimeIdentityV2Response {
        val bytes=CBOR.toBytes(map)
        val header=byteArrayOf(9,0,(bytes.size shr 8).toByte(),bytes.size.toByte(),0x80.toByte(),0x40,0,command.toByte())
        return McuMgrResponse.buildResponse(McuMgrScheme.BLE,header+bytes,RuntimeIdentityV2Response::class.java)
    }
    private fun value(loader:Map<String,Any> = mapOf("kind" to LoaderContract.COMMON,"digest" to ByteArray(32){0xab.toByte()},"anchor_sha256" to ByteArray(32){0xcd.toByte()}))=
        mapOf("protocol" to 2,"model" to "VIMAR30805","layout" to 2,"uid" to listOf(0xffffffffL,1L),"loader" to loader)
    @Test fun actualNordicFramedRead1PreservesTypedDigestAndSeparateAnchor() {
        val identity=wire(value()).identity()
        assertEquals(2,identity.protocol);assertEquals("",identity.loaderSha256)
        assertEquals(LoaderContract(LoaderContract.COMMON,"ab".repeat(32)),identity.typedLoader)
        assertEquals("cd".repeat(32),identity.anchorSha256)
        assertEquals(listOf("ffffffff","00000001"),identity.uid)
    }
    @Test fun commandMismatchAndMalformedContractCannotDowngradeToRead0() {
        for(map in listOf(value(mapOf("kind" to "unknown","digest" to ByteArray(32))),value(mapOf("kind" to LoaderContract.COMMON,"digest" to ByteArray(32))),
            value(mapOf("kind" to LoaderContract.LEGACY,"digest" to ByteArray(32),"anchor_sha256" to ByteArray(32))))) {
            assertThrows(IllegalArgumentException::class.java){wire(map).identity()}
        }
        assertThrows(IllegalArgumentException::class.java){wire(value(),0).identity()}
        for(rc in listOf<Any>("8",8.9,true))assertThrows(Exception::class.java){wire(mapOf("rc" to rc)).rejection()}
        assertTrue(wire(mapOf("rc" to 8)).rejection() is org.openvimar.updater.core.IdentityCommandUnavailable)
        assertFalse(wire(mapOf("rc" to 6)).rejection() is org.openvimar.updater.core.IdentityCommandUnavailable)
    }
    @Test fun actualManagerSendsRead1WithEmptyMapAndLeavesRead0Distinct() {
        val packets=mutableListOf<ByteArray>()
        val transport=object:McuMgrTransport {
            override fun getScheme()=McuMgrScheme.BLE
            override fun <T:McuMgrResponse> send(bytes:ByteArray,timeout:Long,type:Class<T>):T=error("Synchronous send unused")
            override fun <T:McuMgrResponse> send(bytes:ByteArray,timeout:Long,type:Class<T>,callback:McuMgrCallback<T>){packets+=bytes}
            override fun connect(callback:McuMgrTransport.ConnectionCallback?){}
            override fun release(){}
            override fun addObserver(observer:McuMgrTransport.ConnectionObserver){}
            override fun removeObserver(observer:McuMgrTransport.ConnectionObserver){}
        }
        val manager=RuntimeIdentityManager(transport)
        manager.readV2(object:McuMgrCallback<RuntimeIdentityV2Response>{
            override fun onResponse(response:RuntimeIdentityV2Response){}
            override fun onError(error:io.runtime.mcumgr.exception.McuMgrException){}
        })
        manager.read(object:McuMgrCallback<RuntimeIdentityResponse>{
            override fun onResponse(response:RuntimeIdentityResponse){}
            override fun onError(error:io.runtime.mcumgr.exception.McuMgrException){}
        })
        assertEquals(listOf(1,0),packets.map{it[7].toInt()})
        for(packet in packets){assertEquals(0,packet[0].toInt() and 7);assertEquals(0x80,packet[4].toInt() and 255);assertEquals(0x40,packet[5].toInt());assertTrue(StrictSmpCbor.decode(packet.copyOfRange(8,packet.size)).isEmpty())}
    }
}
