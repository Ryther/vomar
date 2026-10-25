package org.openvimar.updater

import org.junit.Assert.*
import org.junit.Test
import org.openvimar.updater.core.*

class UpdateCopyTest {
    @Test fun phasesExplainTheOperationInsteadOfInternalEnumNames() {
        val phases = mapOf(
            Phase.UPLOAD_MIGRATION to "recovery",
            Phase.UPLOAD_MAIN to "firmware"
        )
        phases.forEach { (phase, subject) ->
            val copy = UpdateCopy.describe(UpdateEvent.Progress(phase, 37, 100))
            assertTrue(copy.contains(subject))
            assertTrue(copy.contains("37%"))
            assertFalse(copy.contains(phase.name))
        }
        Decision.entries.forEach { decision ->
            val copy = UpdateCopy.describe(UpdateEvent.Planned(decision))
            assertFalse(copy.contains(decision.name))
            assertTrue(copy.isNotBlank())
        }
    }

    @Test fun lostResetAcknowledgementDoesNotClaimTheDimmerRestarted() {
        val copy = UpdateCopy.describe(UpdateEvent.AwaitingOperator(false))
        assertTrue(copy.contains("Firmware verified"))
        assertTrue(copy.contains("restart was not acknowledged"))
        assertTrue(copy.contains("Home Assistant"))
        assertFalse(copy.contains("Update completed"))
    }

    @Test fun acknowledgedResetStillRequiresOnlineConfirmation() {
        val copy = UpdateCopy.describe(UpdateEvent.AwaitingOperator(true))
        assertTrue(copy.contains("restart request"))
        assertTrue(copy.contains("online"))
        assertFalse(copy.contains("Update completed"))
    }

    @Test fun rejectedImagesExplainTheBlockWithoutSuggestingAForcedRetry() {
        val copy = UpdateCopy.failure("Unexpected recovery or primary image")
        assertTrue(copy.contains("does not match"))
        assertTrue(copy.contains("Export the report"))
        assertFalse(copy.contains("Unexpected"))
        assertFalse(copy.contains("Resume"))
    }

    @Test fun unknownFailuresKeepDiagnosticDetailWithoutInventingACause() {
        val copy = UpdateCopy.failure("vendor error 139")
        assertTrue(copy.contains("Export the report"))
        assertTrue(copy.contains("Technical detail: vendor error 139"))
        assertFalse(copy.contains("wrong code"))
    }

    @Test fun retryDelayNamesTheConnectionInsteadOfAnUpdateResult() {
        val copy = UpdateCopy.describe(UpdateEvent.Reconnecting(2, 5_000))
        assertTrue(copy.contains("reconnect"))
        assertTrue(copy.contains("5 s"))
        assertTrue(copy.contains("2 of 3"))
    }

    @Test fun longTechnicalDetailsStayInTheReportTextWithoutHidingTheNextActionOnScreen() {
        val reportText = UpdateCopy.failure("vendor error " + "139 ".repeat(100))
        assertTrue(reportText.contains("vendor error"))
        val visible = UpdateCopy.visibleStatus(reportText)
        assertTrue(visible.contains("Export the report"))
        assertFalse(visible.contains("vendor error"))
        assertEquals("Connessione in corso…", UpdateCopy.visibleStatus("Connessione in corso…"))
    }
}
