package org.openvimar.updater

import org.junit.Assert.*
import org.junit.Test
import java.io.IOException

class DkBackupCaptureTest {
    private val chip=DkBackupIdentity(0x12345678,0xabcdef01,0x52840)
    private class Source(private val chip: DkBackupIdentity): DkBackupSource {
        override val identity=chip
        var identities=0
        var reads=0
        var changeIdentity=false
        var mismatchSecond=false
        override fun currentIdentity()=chip.also { identities++ }.let {
            if(changeIdentity&&identities>=2) it.copy(uid0=0) else it
        }
        override fun readBlock(region: DkBackupRegion,offset: Int,length: Int): ByteArray {
            assertTrue(length in 4..512&&length%4==0&&offset%4==0)
            assertTrue(offset+length<=region.size&&(offset%1024)+length<=1024)
            reads++
            return ByteArray(length) { ((offset+it)%251).toByte() }.also {
                if(mismatchSecond&&reads>2064)it[0]=(it[0].toInt() xor 1).toByte()
            }
        }
    }
    private fun reject(action: () -> Unit) {
        try { action();fail("Incomplete backup accepted") } catch (_: IOException) { }
    }

    @Test fun collectsTwoCompletePassesWithBoundedMonotonicProgress() {
        val source=Source(chip)
        var previous=0L
        var events=0
        val captured=DkBackupCapture.read(source,progress={ event ->
            assertTrue(event.completedBytes>previous&&event.completedBytes-previous<=512)
            previous=event.completedBytes;events++
        })
        assertEquals(4128,source.reads)
        assertEquals(4,source.identities)
        assertEquals(4128,events)
        assertEquals(2L*(0x100000+8192),previous)
        for(region in DkBackupRegion.entries) {
            assertEquals(region.size,captured.first.regions.getValue(region).size)
            assertArrayEquals(captured.first.regions.getValue(region),captured.second.regions.getValue(region))
        }
    }

    @Test fun cancellationAtABlockBoundaryReturnsNoCaptureOrFurtherReads() {
        val source=Source(chip)
        var cancelled=false
        reject { DkBackupCapture.read(source,cancelled={cancelled},progress={cancelled=true}) }
        assertEquals(1,source.reads)
        assertEquals(1,source.identities)
    }

    @Test fun rejectsTargetChangesAndSecondPassMismatch() {
        val changing=Source(chip).apply { changeIdentity=true }
        reject { DkBackupCapture.read(changing) }
        assertEquals(2064,changing.reads)
        val mismatch=Source(chip).apply { mismatchSecond=true }
        reject { DkBackupCapture.read(mismatch) }
        assertEquals(2065,mismatch.reads)
    }

    @Test fun collectorRejectsDuplicatedMisalignedMissingAndOutOfOrderBlocks() {
        val collector=DkBackupCollector()
        collector.accept(DkBackupRegion.FLASH,0,ByteArray(512))
        reject { collector.accept(DkBackupRegion.FLASH,0,ByteArray(512)) }
        reject { collector.accept(DkBackupRegion.FLASH,514,ByteArray(4)) }
        reject { collector.accept(DkBackupRegion.FLASH,1024,ByteArray(512)) }
        reject { collector.finish(chip,chip) }
    }

    @Test fun changedFlashReportsTheExactFirstAddressAndBlockEvidenceWithoutReturningACapture() {
        var identityReads=0
        val source=object:DkBackupSource {
            override val identity=chip
            override fun currentIdentity()=chip.also {identityReads++}
            override fun readBlock(region:DkBackupRegion,offset:Int,length:Int)=ByteArray(length) {0x33}.also {
                if(identityReads>=3 && region==DkBackupRegion.FLASH && offset==0xf8000) {
                    it[17]=0x22;it[300]=0x11
                }
            }
        }
        val error=try {DkBackupCapture.read(source);fail("Changed FLASH accepted");throw AssertionError()}
            catch(error:DkBackupChangedException){error}
        assertEquals(DkBackupRegion.FLASH,error.region)
        assertEquals(0xf8000L,error.blockAddress)
        assertEquals(0xf8011L,error.firstChangedAddress)
        assertEquals(2,error.changedBytesInBlock)
        val digest=java.security.MessageDigest.getInstance("SHA-256")
        fun hex(bytes:ByteArray)=bytes.joinToString(""){"%02x".format(it.toInt() and 255)}
        assertEquals(hex(digest.digest(ByteArray(512){0x33})),error.firstPassBlockSha256)
        assertEquals(hex(digest.digest(ByteArray(512){0x33}.also {it[17]=0x22;it[300]=0x11})),error.secondPassBlockSha256)
        assertTrue(error.message!!.contains("0x000f8011"))
    }
}
