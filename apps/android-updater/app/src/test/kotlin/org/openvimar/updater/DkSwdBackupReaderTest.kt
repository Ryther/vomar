package org.openvimar.updater

import org.junit.Assert.*
import org.junit.Test
import java.io.IOException

class DkSwdBackupReaderTest {
    private fun rejected(action: () -> Unit): String {
        try { action();fail("Unsafe/incomplete backup read accepted") } catch(error: IOException) { return error.message.orEmpty() }
        return ""
    }
    private fun model()=DkSwdReadOnlyTest.TargetModel()

    @Test fun batchesPostedApReadsAndRdbuffIntoLiteralExpectedWords() {
        val device=model()
        val source=DkSwdBackup.open(device)
        assertArrayEquals(byteArrayOf(0,0,0xa5.toByte(),0xa5.toByte(),4,0,0xa5.toByte(),0xa5.toByte(),
            8,0,0xa5.toByte(),0xa5.toByte(),12,0,0xa5.toByte(),0xa5.toByte()),source.readBlock(DkBackupRegion.FLASH,0,16))
        assertTrue(device.bitCounts.contains(270))
        assertTrue(device.debugWrites.all { (ap,address,_) -> !ap||address in listOf(0,4) })
    }

    @Test fun enforces128WordAndOneKibTarBoundsBeforeSending() {
        val device=model();val source=DkSwdBackup.open(device)
        val maximum=source.readBlock(DkBackupRegion.FLASH,0,512)
        assertEquals(512,maximum.size)
        assertTrue(device.bitCounts.contains(6966))
        source.readBlock(DkBackupRegion.FLASH,0x200,512)
        source.readBlock(DkBackupRegion.FLASH,0x400,512)
        assertTrue(device.debugWrites.contains(Triple(true,4,0x400L)))
        val before=device.commands.size
        for((offset,length) in listOf(0 to 516,0x3fc to 8,2 to 4,0x100000 to 4,0 to 0,-4 to 4))
            assertTrue(rejected { source.readBlock(DkBackupRegion.FLASH,offset,length) }.isNotEmpty())
        assertEquals(before,device.commands.size)
    }

    @Test fun readsLastWordsOfEachAllowedRegionWithoutWrapping() {
        val device=model();val source=DkSwdBackup.open(device)
        for(region in DkBackupRegion.entries) {
            source.readBlock(region,region.size-4,4)
            assertTrue(device.memoryReads.contains(region.start+region.size-4))
        }
        assertTrue(device.memoryReads.all { address -> address in 0..0xfffffL||address in 0x10000000L..0x10001fffL })
    }

    @Test fun discardsWaitBatchAndRestoresTarBeforeRetrying() {
        val device=model();val source=DkSwdBackup.open(device)
        device.batchWaitAt=1;device.batchWaitTimes=1
        val actual=source.readBlock(DkBackupRegion.FLASH,0,16)
        assertEquals(0,actual[0].toInt())
        assertEquals(12,actual[12].toInt())
        assertEquals(2,device.bitCounts.count { it==270 })
        val exhausted=model();val second=DkSwdBackup.open(exhausted)
        exhausted.batchWaitAt=1;exhausted.batchWaitTimes=10
        assertTrue(rejected { second.readBlock(DkBackupRegion.FLASH,0,16) }.contains("WAIT"))
        assertEquals(3,exhausted.bitCounts.count { it==270 })
    }

    @Test fun rejectsFaultParityAndDisplacedDataWithoutReturningABlock() {
        val fault=model();val a=DkSwdBackup.open(fault);fault.batchFaultAt=1
        assertTrue(rejected { a.readBlock(DkBackupRegion.FLASH,0,16) }.contains("FAULT"))
        val parity=model();val b=DkSwdBackup.open(parity);parity.batchParityAt=2
        assertTrue(rejected { b.readBlock(DkBackupRegion.FLASH,0,16) }.contains("parity"))
        val shifted=model();val c=DkSwdBackup.open(shifted);shifted.shiftedBatch=true
        assertTrue(rejected { c.readBlock(DkBackupRegion.FLASH,0,16) }.contains("sentinel"))
    }

    @Test fun cancellationAndDeadlineStopBeforeTheNextBlockCommand() {
        val device=model();var cancelled=false
        val source=DkSwdBackup.open(device,cancelled={cancelled})
        cancelled=true
        val commands=device.commands.size
        assertTrue(rejected { source.readBlock(DkBackupRegion.FLASH,0,512) }.contains("cancelled"))
        assertEquals(commands,device.commands.size)
        val late=model();var clock=0L
        val reader=DkSwdBackup.open(late,now={clock})
        clock=21L*60*1_000_000_000
        val before=late.commands.size
        assertTrue(rejected { reader.readBlock(DkBackupRegion.FLASH,0,512) }.contains("timed out"))
        assertEquals(before,late.commands.size)
    }
}
