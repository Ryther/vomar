package org.openvimar.updater

import org.junit.Assert.*
import org.junit.Test

class UiPolicyTest {
    private val pkg = PackageSummary("Studio", "0.5.8", "AA:BB:CC:DD:EE:FF", listOf("11111111", "22222222"), "a".repeat(64), "b".repeat(64), "0.1.0")
    private val ready = SessionPresentation(inspected = true, loaded = true, packageSummary = pkg)

    @Test fun initialInspectionAndUnboundActivityCannotOfferDeviceActions() {
        assertEquals(PrimaryAction.NONE, UiPolicy.actions(SessionPresentation(), true, true).primary)
        assertEquals(PrimaryAction.NONE, UiPolicy.actions(ready, true, false).primary)
        assertFalse(UiPolicy.actions(ready, true, false).canProbe)
    }

    @Test fun emptyOrUnreadableSessionAllowsImportInsteadOfUpdate() {
        for (state in listOf(SessionPresentation(inspected=true,loaded=true), ready.copy(loaded=false))) {
            val actions = UiPolicy.actions(state, true, true)
            assertEquals(PrimaryAction.IMPORT, actions.primary)
            assertFalse(actions.canProbe)
            assertFalse(actions.canResume)
            assertFalse(actions.canConfirm)
        }
    }

    @Test fun permissionsPrecedeBluetoothButDoNotBlockManualOutcomeOrExport() {
        assertEquals(PrimaryAction.PERMISSIONS, UiPolicy.actions(ready, false, true).primary)
        assertEquals(PrimaryAction.CONFIRM_ONLINE, UiPolicy.actions(ready.copy(imagesVerified=true,hasCheckpoint=true), false, true).primary)
        assertEquals(PrimaryAction.EXPORT, UiPolicy.actions(ready.copy(imagesVerified=true,operatorOnline=true,reportAvailable=true), false, true).primary)
    }

    @Test fun savedSessionOffersResumeInsteadOfAnotherFreshStart() {
        assertEquals(PrimaryAction.START, UiPolicy.actions(ready, true, true).primary)
        assertEquals(PrimaryAction.RESUME, UiPolicy.actions(ready.copy(hasCheckpoint=true), true, true).primary)
    }

    @Test fun runningOperationsExposeOnlyAnApplicableStop() {
        SessionOperation.entries.filter { it != SessionOperation.IDLE }.forEach { operation ->
            val actions = UiPolicy.actions(ready.copy(busy=true,operation=operation,reportAvailable=true), true, true)
            assertEquals(PrimaryAction.NONE, actions.primary)
            assertFalse(actions.canImport || actions.canProbe || actions.canExport || actions.canConfirm)
            assertEquals(operation in listOf(SessionOperation.UPDATE,SessionOperation.PROBE,SessionOperation.IMPORT), actions.canStop)
        }
    }

    @Test fun confirmedImagesDoNotPretendThatZigbeeIsOnline() {
        val state = ready.copy(imagesVerified=true,hasCheckpoint=true,resetAcknowledged=false)
        val actions = UiPolicy.actions(state, true, true)
        assertEquals(PrimaryAction.CONFIRM_ONLINE, actions.primary)
        assertTrue(actions.canConfirm)
        assertTrue(actions.canResume)
        assertFalse(UiPolicy.actions(ready, true, true).canConfirm)
        assertFalse(UiPolicy.actions(state.copy(operatorOnline=true), true, true).canResume)
    }

    @Test fun exportingRequiresAnActualReport() {
        assertFalse(UiPolicy.actions(ready, true, true).canExport)
        assertTrue(UiPolicy.actions(ready.copy(reportAvailable=true), true, true).canExport)
    }

    @Test fun uncertainVerifiedResetStillHasAPermissionPathWithoutAuthorizingResume() {
        val state = ready.copy(imagesVerified=true,hasCheckpoint=true,resetAcknowledged=false)
        val blocked = UiPolicy.actions(state,false,true)
        assertTrue(blocked.canRequestResumePermission)
        assertFalse(blocked.canResume)
        assertTrue(UiPolicy.actions(state,true,true).canResume)
        assertFalse(UiPolicy.actions(state.copy(resetAcknowledged=true),false,true).canRequestResumePermission)
    }

    @Test fun manualOnlineConfirmationCanBeCorrectedAndInitialImportCanBeStopped() {
        assertTrue(UiPolicy.actions(ready.copy(imagesVerified=true,operatorOnline=true),true,true).canConfirm)
        assertTrue(UiPolicy.actions(SessionPresentation(busy=true,operation=SessionOperation.IMPORT),false,true).canStop)
    }

    @Test fun offlineAfterAcknowledgedResetCanGrantPermissionsForReadOnlyDiagnosis() {
        val state=ready.copy(imagesVerified=true,hasCheckpoint=true,resetAcknowledged=true,operatorOnline=false)
        assertTrue(UiPolicy.actions(state,false,true).canRequestProbePermission)
        assertFalse(UiPolicy.actions(state,false,true).canProbe)
        assertTrue(UiPolicy.actions(state,true,true).canProbe)
    }
}
