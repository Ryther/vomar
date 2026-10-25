package org.openvimar.updater

import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.nio.file.Files
import java.security.MessageDigest

class FleetReleaseCacheTest {
    private fun hash(bytes:ByteArray)=MessageDigest.getInstance("SHA-256").digest(bytes).joinToString(""){"%02x".format(it.toInt() and 255)}
    @Test fun onlyVerifiedExactBytesEnterPrivateCacheAndCancellationLeavesNoCandidate() {
        val dir=Files.createTempDirectory("release-cache").toFile();val bytes=ByteArray(12000){it.toByte()};var validations=0
        val cache=FleetReleaseCache(dir,20000){file->validations++;FleetReleaseRef(hash(file.readBytes()),"0.8.0","b".repeat(64),file.path)}
        var progress=0L;val ref=cache.import(ByteArrayInputStream(bytes),checkActive={},progress={progress=it})
        assertEquals(hash(bytes),ref.digest);assertArrayEquals(bytes,java.io.File(ref.cachePath).readBytes());assertEquals(12000,progress.toInt())
        var checks=0
        try{cache.import(ByteArrayInputStream(bytes),checkActive={if(++checks>2)throw java.io.IOException("Cancelled")});fail("Cancellation ignored")}catch(_:java.io.IOException){}
        assertEquals(1,validations);assertEquals(listOf(ref.digest+".zip"),dir.list()!!.toList())
        dir.deleteRecursively()
    }
    @Test fun oversizeUntrustedAndDigestMismatchCannotBecomeASelectedRelease() {
        val dir=Files.createTempDirectory("release-cache").toFile()
        val cache=FleetReleaseCache(dir,10){file->FleetReleaseRef("0".repeat(64),"0.8.0","b".repeat(64),file.path)}
        for(bytes in listOf(ByteArray(11),ByteArray(3))){try{cache.import(ByteArrayInputStream(bytes));fail("Untrusted release accepted")}catch(_:Exception){}}
        assertTrue(dir.list()!!.isEmpty());dir.deleteRecursively()
    }
}
