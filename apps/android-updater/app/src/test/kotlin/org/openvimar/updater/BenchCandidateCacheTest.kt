package org.openvimar.updater

import java.io.File
import java.nio.file.Files
import java.security.MessageDigest
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec
import org.openvimar.installer.CandidateRelease
import org.openvimar.installer.CommonRelease
import org.openvimar.updater.core.CommonPackageReader
import org.junit.Assert.*
import org.junit.Test

class BenchCandidateCacheTest {
    @Test fun actualSignedUnqualifiedCandidateCachesForInspectionButNormalVerifierRejectsIt() {
        val fixtures=File("../../../tools/android/test-fixtures/common-v3-candidate")
        val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(File(fixtures,"public.der").readBytes()))
        val bytes=File(fixtures,"qualification-candidate.zip").readBytes()
        val directory=Files.createTempDirectory("real-bench-cache").toFile()
        try {
            val cache=BenchCandidateCache(directory,2*1024*1024){raw->
                val candidate=CandidateRelease.inspect(raw,key,"0.6.0")
                BenchCandidateRef(candidate.releaseSha256,candidate.familySha256,"")
            }
            val ref=cache.import(bytes.inputStream());val candidate=CandidateRelease.inspect(cache.read(ref),key,"0.6.0")
            assertEquals(hash(bytes),candidate.releaseSha256)
            assertEquals(ref.familySha256,candidate.familySha256)
            assertThrows(IllegalArgumentException::class.java){CommonRelease.verify(bytes,key,"0.6.0")}
            assertThrows(Exception::class.java){CommonPackageReader.read(bytes.inputStream())}
            assertEquals(listOf(ref.digest+".zip"),directory.listFiles()!!.map{it.name})
            val changed=candidate.qualification().apply{this[0]=0}
            assertFalse(changed.contentEquals(candidate.qualification()))
        } finally {directory.deleteRecursively()}
    }
    private fun hash(bytes:ByteArray)=MessageDigest.getInstance("SHA-256").digest(bytes).joinToString(""){"%02x".format(it.toInt() and 255)}
    private fun cache(directory:File,limit:Int=64)=BenchCandidateCache(directory,limit){bytes->
        require(bytes.firstOrNull()==1.toByte()){"Candidate verifier refused"}
        BenchCandidateRef(hash(bytes),"b".repeat(64),"")
    }
    @Test fun onlyValidatedExactBytesBecomeReadOnlyPrivateCandidateReferences() {
        val directory=Files.createTempDirectory("bench-cache").toFile()
        try {
            val bytes=byteArrayOf(1,2,3);val ref=cache(directory).import(bytes.inputStream())
            assertEquals(hash(bytes),ref.digest);assertEquals("b".repeat(64),ref.familySha256)
            assertArrayEquals(bytes,cache(directory).read(ref))
            assertEquals(listOf(ref.digest+".zip"),directory.listFiles()!!.map{it.name})
            File(ref.cachePath).writeBytes(byteArrayOf(1,2,4))
            assertThrows(IllegalArgumentException::class.java){cache(directory).read(ref)}
        } finally {directory.deleteRecursively()}
    }
    @Test fun FailedValidationOrOversizeDoesNotPublishAnyCandidate() {
        val directory=Files.createTempDirectory("bench-cache").toFile()
        try {
            assertThrows(IllegalArgumentException::class.java){cache(directory).import(byteArrayOf(0,1).inputStream())}
            assertThrows(IllegalArgumentException::class.java){cache(directory,2).import(byteArrayOf(1,2,3).inputStream())}
            assertTrue(directory.listFiles()!!.isEmpty())
        } finally {directory.deleteRecursively()}
    }
    @Test fun cancellationAfterValidationKeepsPriorCacheAndPublishesNoApprovalState() {
        val directory=Files.createTempDirectory("bench-cache").toFile()
        try {
            val old=cache(directory).import(byteArrayOf(1,1).inputStream());var validated=false
            val candidate=BenchCandidateCache(directory,64){bytes->validated=true;BenchCandidateRef(hash(bytes),"b".repeat(64),"")}
            assertThrows(IllegalStateException::class.java){candidate.import(byteArrayOf(1,2).inputStream(),{if(validated)error("cancelled")})}
            assertEquals(listOf(old.digest+".zip"),directory.listFiles()!!.map{it.name})
            assertArrayEquals(byteArrayOf(1,1),cache(directory).read(old))
        } finally {directory.deleteRecursively()}
    }
    @Test fun referenceCannotReadOutsidePrivateDirectoryOrClaimAnotherDigest() {
        val directory=Files.createTempDirectory("bench-cache").toFile()
        try {
            val ref=cache(directory).import(byteArrayOf(1,2).inputStream())
            assertThrows(IllegalArgumentException::class.java){cache(directory).read(ref.copy(cachePath=File(directory.parentFile,"elsewhere.zip").path))}
            assertThrows(IllegalArgumentException::class.java){cache(directory).read(ref.copy(digest="a".repeat(64)))}
        } finally {directory.deleteRecursively()}
    }
}
