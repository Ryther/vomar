package org.openvimar.updater.ble

import org.junit.Assert.*
import org.junit.Test
import io.runtime.mcumgr.util.CBOR
import io.runtime.mcumgr.McuMgrScheme
import io.runtime.mcumgr.response.McuMgrResponse

class RuntimeIdentityTest {
    private fun response(bytes:ByteArray):RuntimeIdentityResponse {
        val header=byteArrayOf(9,0,(bytes.size shr 8).toByte(),bytes.size.toByte(),0x80.toByte(),0x40,0,0)
        return McuMgrResponse.buildResponse(McuMgrScheme.BLE,header+bytes,RuntimeIdentityResponse::class.java)
    }
    @Test fun decodesFirmwareCborIdentityIncludingUnsignedUidWords() {
        val bytes=CBOR.toBytes(mapOf("protocol" to 1,"model" to "VIMAR30805","layout" to 2,
            "uid" to listOf(0x11223344L,0xffffffffL),"loader_sha256" to ByteArray(32){0xab.toByte()}))
        val identity=response(bytes).identity()
        assertEquals(listOf("11223344","ffffffff"),identity.uid)
        assertEquals("ab".repeat(32),identity.loaderSha256)
    }
    @Test fun missingOrMalformedIdentityCannotBecomeAnAuthorizedTarget() {
        for(map in listOf(emptyMap<String,Any>(),mapOf("protocol" to 1,"model" to "VIMAR30805","layout" to 2,
            "uid" to listOf(-1L,2L),"loader_sha256" to ByteArray(32)),mapOf("protocol" to 1,"model" to "VIMAR30805","layout" to 2,
            "uid" to listOf(1L,2L),"loader_sha256" to ByteArray(31)))) {
            val response=response(CBOR.toBytes(map))
            assertThrows(IllegalArgumentException::class.java){response.identity()}
        }
    }
    @Test fun onlyExplicitUnsupportedCommandEnablesTheLegacyBridgeFallback() {
        val unsupported=response(CBOR.toBytes(mapOf("rc" to 8)))
        assertTrue(unsupported.rejection() is org.openvimar.updater.core.IdentityCommandUnavailable)
        for(rc in listOf(1,4,6,13)) {
            val error=response(CBOR.toBytes(mapOf("rc" to rc)))
            assertFalse(error.rejection() is org.openvimar.updater.core.IdentityCommandUnavailable)
        }
        val groupError=response(CBOR.toBytes(mapOf("rc" to 8,"err" to mapOf("group" to 0x8040,"rc" to 1))))
        assertNotNull(groupError.groupReturnCode)
        assertFalse(groupError.rejection() is org.openvimar.updater.core.IdentityCommandUnavailable)
    }
    @Test fun malformedReturnCodeAndCoercedIdentityScalarsDoNotGainAuthority() {
        for(value in listOf("8",8.9)){val r=response(CBOR.toBytes(mapOf("rc" to value)));assertThrows(IllegalArgumentException::class.java){r.rejection()}}
        val map=mapOf("protocol" to "1","model" to "VIMAR30805","layout" to 2,"uid" to listOf(1L,2L),"loader_sha256" to ByteArray(32))
        val r=response(CBOR.toBytes(map));assertThrows(IllegalArgumentException::class.java){r.identity()}
    }

}
