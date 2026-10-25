package org.openvimar.updater

import org.junit.Assert.*
import org.junit.Test

class DkDiagnosticPresentationTest {
    @Test fun successfulBackupRendersWithoutAnyUsbProbeSection() {
        val text=DkDiagnosticPresentation.format(DkDiagnosticReportView("dk-backup-request","{backup metadata}",true,
            backupPhase="COMPLETE",backupOutcome="VERIFIED",backupMessage="Verified backup ready to save"))
        assertTrue(text.contains("Verified backup ready to save"))
        assertTrue(text.contains("COMPLETE"))
        assertTrue(text.contains("{backup metadata}"))
        assertFalse(text.contains("USB communication verified"))
    }
    @Test fun pendingBackupAndPartialFailureRemainReadableWithoutProbeData() {
        val pending=DkDiagnosticPresentation.format(DkDiagnosticReportView("dk-backup-request","{pending}"))
        assertTrue(pending.contains("Backup pending"))
        val failed=DkDiagnosticPresentation.format(DkDiagnosticReportView("dk-backup-request","{progress:512}",false,
            backupPhase="ACQUIRING",backupOutcome="FAILED",backupMessage="SWD WAIT retry limit reached",error="SWD WAIT retry limit reached"))
        assertTrue(failed.contains("ACQUIRING"))
        assertTrue(failed.contains("SWD WAIT retry limit reached"))
        assertTrue(failed.contains("{progress:512}"))
    }
    @Test fun ordinaryUsbReportKeepsItsProbeSummary() {
        val text=DkDiagnosticPresentation.format(DkDiagnosticReportView("dk-usb-read-only","{usb}",true,
            probeFirmware="J-Link OB",targetVoltage="3.300 V"))
        assertTrue(text.contains("J-Link: J-Link OB"))
        assertTrue(text.contains("Reference voltage: 3.300 V"))
        assertTrue(text.contains("USB communication verified"))
        assertTrue(text.endsWith("{usb}"))
    }
    @Test fun ordinarySwdReportKeepsSiliconIdentityAndCommercialModelLimit() {
        val text=DkDiagnosticPresentation.format(DkDiagnosticReportView("dk-swd-read-only","{swd}",true,
            probeFirmware="J-Link OB",targetVoltage="3.300 V",targetChip="nRF52840",uid="[uid0,uid1]"))
        assertTrue(text.contains("Target chip: nRF52840"))
        assertTrue(text.contains("FICR UID: [uid0,uid1]"))
        assertTrue(text.contains("does not confirm a Vimar commercial model"))
    }
    @Test fun missingOptionalSectionsAndOrdinaryFailureFallBackToTheReport() {
        assertEquals("{missing sections}",DkDiagnosticPresentation.format(DkDiagnosticReportView("dk-usb-read-only","{missing sections}",true)))
        assertEquals("{missing identity}",DkDiagnosticPresentation.format(DkDiagnosticReportView("dk-swd-read-only","{missing identity}",true,probeFirmware="J-Link OB")))
        assertEquals("{USB failed}",DkDiagnosticPresentation.format(DkDiagnosticReportView("dk-usb-read-only","{USB failed}",false,error="Disconnected")))
    }
}
