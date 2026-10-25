package org.openvimar.updater.ble

import org.junit.Assert.*
import org.junit.Test
import org.openvimar.updater.core.MigrationBootCommandUnavailable
import io.runtime.mcumgr.*
import io.runtime.mcumgr.response.McuMgrResponse
import io.runtime.mcumgr.util.CBOR

class MigrationBootResponseTest {
    private fun response(payload:ByteArray):MigrationBootResponse {
        val header=byteArrayOf(11,0,(payload.size shr 8).toByte(),payload.size.toByte(),0x80.toByte(),0x42,0,0)
        return McuMgrResponse.buildResponse(McuMgrScheme.BLE,header+payload,MigrationBootResponse::class.java)
    }
    @Test fun explicitAcceptanceRequiredAndOnlyGlobalEnotsupIsClassifiedUnsupported() {
        for(map in listOf(emptyMap<String,Any>(),mapOf("accepted" to false)))try{response(CBOR.toBytes(map)).acknowledgement();fail("Missing/refused acceptance accepted")}catch(_:IllegalArgumentException){}
        response(CBOR.toBytes(mapOf("accepted" to true))).acknowledgement()
        assertTrue(response(CBOR.toBytes(mapOf("rc" to 8))).rejection() is MigrationBootCommandUnavailable)
        assertFalse(response(CBOR.toBytes(mapOf("rc" to 3))).rejection() is MigrationBootCommandUnavailable)
    }
    @Test fun originalRawPayloadTypesDuplicatesAndTrailingDataCannotGrantAckOrUnsupportedFallback() {
        for(value in listOf("true",1)){val r=response(CBOR.toBytes(mapOf("accepted" to value)));assertThrows(IllegalArgumentException::class.java){r.acknowledgement()}}
        for(value in listOf("8",8.9)){val r=response(CBOR.toBytes(mapOf("rc" to value)));assertThrows(IllegalArgumentException::class.java){r.rejection()}}
        for(bytes in listOf(byteArrayOf(0xa2.toByte(),0x62,0x72,0x63,8,0x62,0x72,0x63,8),CBOR.toBytes(mapOf("rc" to 8))+byteArrayOf(0))) {
            val r=response(bytes);assertThrows(IllegalArgumentException::class.java){r.rejection()}
        }
    }
    @Test fun nordicManagerEncodesOnlyTheExactBinaryHashWithPurposeGroupAndWriteCommand() {
        var packet:ByteArray?=null
        val transport=object:McuMgrTransport {
            override fun getScheme()=McuMgrScheme.BLE
            override fun <T:McuMgrResponse> send(bytes:ByteArray,timeout:Long,type:Class<T>):T=error("Synchronous send not requested")
            override fun <T:McuMgrResponse> send(bytes:ByteArray,timeout:Long,type:Class<T>,callback:McuMgrCallback<T>){packet=bytes}
            override fun connect(callback:McuMgrTransport.ConnectionCallback?){}
            override fun release(){}
            override fun addObserver(observer:McuMgrTransport.ConnectionObserver){}
            override fun removeObserver(observer:McuMgrTransport.ConnectionObserver){}
        }
        MigrationBootManager(transport).boot("ab".repeat(32),object:McuMgrCallback<MigrationBootResponse>{
            override fun onResponse(response:MigrationBootResponse){}
            override fun onError(error:io.runtime.mcumgr.exception.McuMgrException){}
        })
        val bytes=packet!!;assertEquals(2,bytes[0].toInt() and 7);assertEquals(1,(bytes[0].toInt() shr 3) and 3)
        assertEquals(0x80,bytes[4].toInt() and 255);assertEquals(0x42,bytes[5].toInt() and 255);assertEquals(0,bytes[7].toInt())
        val payload=CBOR.toObject(bytes.copyOfRange(8,bytes.size),Map::class.java)
        assertEquals(setOf("hash"),payload.keys);assertArrayEquals(ByteArray(32){0xab.toByte()},payload["hash"] as ByteArray)
        val response=response(CBOR.toBytes(mapOf("accepted" to true)));response.acknowledgement()
        val group=response(CBOR.toBytes(mapOf("rc" to 8,"err" to mapOf("group" to 0x8042,"rc" to 1))))
        assertFalse(group.rejection() is MigrationBootCommandUnavailable)
    }
}
