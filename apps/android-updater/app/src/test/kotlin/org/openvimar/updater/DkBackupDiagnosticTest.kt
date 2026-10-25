package org.openvimar.updater

import java.io.IOException
import org.junit.Assert.*
import org.junit.Test

class DkBackupDiagnosticTest {
    @Test fun onlyTheMatchingRequestCanContributeDiagnosticFields() {
        val snapshot=DkBackupDiagnostic("attempt-a").completed()
        assertNull(snapshot.fieldsFor(null))
        assertNull(snapshot.fieldsFor("attempt-b"))
        assertEquals(true,snapshot.fieldsFor("attempt-a")!!["success"])
        // A new attempt starts without the previous one's completion evidence.
        val next=DkBackupDiagnostic("attempt-b").fieldsFor("attempt-b")!!
        assertFalse(next.containsKey("success"))
        assertFalse(next.containsKey("error"))
    }

    @Test fun failureRetainsTheLastReadPhaseAndProgressWithoutBackupBytes() {
        val progress=DkBackupProgress(2,DkBackupRegion.FLASH,1_057_280,2_113_536)
        val snapshot=DkBackupDiagnostic("attempt-a")
            .observed("swdLineSynchronizationAttempted",true).observed("part","0x00052840")
            .advanced(progress).failed(IOException("SWD WAIT backup batch retry limit reached"),false)
        val fields=snapshot.fieldsFor("attempt-a")!!
        assertEquals(false,fields["success"])
        assertEquals(true,fields["swdAttempted"])
        assertEquals(true,fields["memoryRead"])
        val backup=fields["backup"] as Map<*,*>
        assertEquals("ACQUIRING",backup["phase"])
        assertEquals("FAILED",backup["outcome"])
        assertEquals("java.io.IOException",backup["errorType"])
        assertEquals("SWD WAIT backup batch retry limit reached",fields["error"])
        assertEquals(mapOf("pass" to 2,"region" to "FLASH","completedBytes" to 1_057_280L,"totalBytes" to 2_113_536L),backup["progress"])
        assertFalse(fields.toString().contains("flash.bin"))
        assertEquals(progress,snapshot.progress)
        assertFalse(snapshot.running)
    }

    @Test fun earlyUsbFailureDoesNotClaimSwdOrMemoryAccess() {
        val snapshot=DkBackupDiagnostic("attempt-a").at(DkBackupPhase.USB_OPEN,"Opening USB")
            .failed(IOException("USB permission is missing"),false)
        val fields=snapshot.fieldsFor("attempt-a")!!
        assertEquals(false,fields["swdAttempted"])
        assertEquals(false,fields["memoryReadAttempted"])
        assertEquals(false,fields["memoryRead"])
        assertEquals("USB_OPEN",(fields["backup"] as Map<*,*>)["phase"])
    }

    @Test fun cancellationRetainsFailurePhaseAndPartialProgress() {
        val progress=DkBackupProgress(1,DkBackupRegion.FLASH,512,2_113_536)
        val snapshot=DkBackupDiagnostic("attempt-a").advanced(progress)
            .failed(IOException("Backup cancelled; no partial archive is available"),true)
        val fields=snapshot.fieldsFor("attempt-a")!!
        assertEquals(false,fields["success"])
        assertEquals("CANCELLED",(fields["backup"] as Map<*,*>)["outcome"])
        assertEquals(progress,snapshot.progress)
    }

    @Test fun privateSnapshotRestoresCorrelatedTerminalEvidenceAfterServiceRecreation() {
        val progress=DkBackupProgress(2,DkBackupRegion.UICR,2_110_000,2_113_536)
        val failed=DkBackupDiagnostic("attempt-a").observed("uid",listOf("0x12345678","0xabcdef01"))
            .observed("swdLineSynchronizationAttempted",true).observed("targetMillivolts",3300)
            .advanced(progress).failed(IOException("USB disconnected"),false)
        val restored=DkBackupDiagnostic.restore(failed.encode())
        assertEquals(failed.fieldsFor("attempt-a"),restored.fieldsFor("attempt-a"))
        assertNull(restored.fieldsFor("attempt-b"))
    }

    @Test fun interruptedRunningSnapshotPreservesPositionWithoutClaimingSuccessOrResuming() {
        val progress=DkBackupProgress(1,DkBackupRegion.FLASH,512,2_113_536)
        val original=DkBackupDiagnostic("attempt-a").advanced(progress)
        val restored=DkBackupDiagnostic.restore(original.encode())
        assertFalse(restored.running)
        assertEquals(progress,restored.progress)
        val fields=restored.fieldsFor("attempt-a")!!
        assertEquals(false,fields["success"])
        assertEquals("INTERRUPTED",(fields["backup"] as Map<*,*>)["outcome"])
        assertTrue((fields["error"] as String).contains("not resumed"))
    }

    @Test fun changedRegionEvidenceSurvivesExportAndServiceRecreationWithoutRawBytes() {
        val error=DkBackupChangedException(DkBackupRegion.FLASH,0xf8000,
            ByteArray(512){0x33},ByteArray(512){0x33}.also {it[17]=0x22})
        val failed=DkBackupDiagnostic("attempt-a").failed(error,false)
        val restored=DkBackupDiagnostic.restore(failed.encode())
        assertEquals(false,restored.fieldsFor("attempt-a")!!["success"])
        assertEquals("FLASH",restored.observations["changedRegion"])
        assertEquals("0x000f8011",restored.observations["firstChangedAddress"])
        assertEquals("0x000f8000",restored.observations["changedBlockAddress"])
        assertEquals(1,restored.observations["changedBytesInBlock"])
        assertEquals(64,(restored.observations["firstPassBlockSha256"] as String).length)
        assertEquals(64,(restored.observations["secondPassBlockSha256"] as String).length)
        assertTrue(restored.observations.values.none {it is ByteArray})
    }
}
