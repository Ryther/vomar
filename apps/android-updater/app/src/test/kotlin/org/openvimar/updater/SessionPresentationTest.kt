package org.openvimar.updater

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import org.openvimar.updater.core.*
import java.io.File
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec

class SessionPresentationTest {
    private class Harness {
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
        val pkg = PackageValidator.validate(PackageReader.read(File("../test-fixtures/synthetic-update.zip").inputStream()),
            KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(File("../test-fixtures/synthetic-public.der").readBytes())), "0.1.0")
        var selected: ValidatedPackage? = pkg
        var nextSelection = pkg
        var checkpoint: Checkpoint? = null
        var corruptPackage = false
        var corruptCheckpoint = false
        var permitted = true
        var operator: Boolean? = null
        var reportExists = false
        var transports = 0; var connects = 0; var saves = 0; var uploads = 0; var resets = 0
        var connectAction: suspend () -> Unit = {}
        var primary = RemoteImage(pkg.manifest.allowedSourceSignedHashes.first(), false, true)
        val controller = SessionController(scope, object : SessionStore {
            override suspend fun load(bundleDigest: String, address: String): Checkpoint? {
                check(!corruptCheckpoint) { "broken checkpoint" }; return checkpoint
            }
            override suspend fun save(checkpoint: Checkpoint) { saves++; this@Harness.checkpoint = checkpoint }
        }, { check(!corruptPackage) { "broken package" }; selected }, { operator }, { _, checkActive, commit -> checkActive(); commit { selected = nextSelection } }, {
            transports++
            object : BleTransport {
                override suspend fun connect(address: String) { connects++; connectAction() }
                override suspend fun images() = RemoteImages(primary, RemoteImage(pkg.manifest.targetRecoverySignedHash, true, true))
                override suspend fun upload(data: ByteArray, onAck: suspend (Int) -> Unit) { uploads++; onAck(data.size); primary = RemoteImage(pkg.manifest.main.signedRegionSha256, false, true) }
                override suspend fun reset(): ResetAck { resets++; return ResetAck.ACKNOWLEDGED }
                override suspend fun close() { }
            }
        }, { _, online, _ -> operator = online; reportExists = true }, { "private diagnostic".toByteArray() }, { permitted }, { reportExists })
        fun checkpoint(phase: Phase) = Checkpoint(bundleDigest=pkg.bundleDigest, bleAddress=pkg.manifest.device.bleAddress, phase=phase)
    }

    @Test fun inspectionLoadsIdentityWithoutPermissionsOrAnyDeviceAccess() = runBlocking {
        val h = Harness(); h.permitted = false
        assertTrue(h.controller.inspect()); h.controller.awaitIdle()
        val ui = h.controller.presentation.value
        assertTrue(ui.inspected); assertTrue(ui.loaded); assertFalse(ui.busy)
        assertEquals(SessionOperation.IDLE, ui.operation)
        assertEquals(h.pkg.manifest.device.name, ui.packageSummary!!.name)
        assertFalse(ui.bluetoothVerified)
        assertEquals(0, h.transports + h.connects + h.saves + h.uploads + h.resets)
        h.scope.cancel()
    }

    @Test fun emptySelectionIsSuccessfullyInspectedWithoutInventingADevice() = runBlocking {
        val h = Harness(); h.selected = null
        h.controller.refresh(); h.controller.awaitIdle()
        val ui = h.controller.presentation.value
        assertTrue(ui.inspected); assertTrue(ui.loaded); assertNull(ui.packageSummary)
        assertFalse(ui.hasCheckpoint); assertFalse(ui.reportAvailable)
        assertEquals(0, h.transports + h.saves)
        h.scope.cancel()
    }

    @Test fun freshMissingZipRetainsAnExistingReportWithoutAnyDeviceAccess() = runBlocking {
        val h = Harness(); h.selected = null; h.reportExists = true
        h.controller.inspect(); h.controller.awaitIdle()
        val ui = h.controller.presentation.value
        assertTrue(ui.inspected); assertTrue(ui.loaded); assertNull(ui.packageSummary)
        assertTrue(ui.reportAvailable)
        assertFalse(ui.imagesVerified); assertFalse(ui.bluetoothVerified)
        assertEquals("private diagnostic", h.controller.report().toString(Charsets.UTF_8))
        assertEquals(0, h.transports + h.connects + h.saves + h.uploads + h.resets)
        h.scope.cancel()
    }

    @Test fun freshCorruptZipFailsClosedButTheExistingReportCanStillBeExported() = runBlocking {
        val h = Harness(); h.corruptPackage = true; h.reportExists = true
        h.controller.inspect(); h.controller.awaitIdle()
        val ui = h.controller.presentation.value
        assertTrue(ui.inspected); assertFalse(ui.loaded); assertNull(ui.packageSummary)
        assertTrue(ui.reportAvailable)
        assertFalse(ui.hasCheckpoint); assertFalse(ui.imagesVerified); assertFalse(ui.bluetoothVerified)
        assertEquals("private diagnostic", h.controller.report().toString(Charsets.UTF_8))
        assertEquals(0, h.transports + h.connects + h.saves + h.uploads + h.resets)
        h.scope.cancel()
    }

    @Test fun restoredPartialAndVerifiedCheckpointsExposeDifferentEvidence() = runBlocking {
        val h = Harness(); h.checkpoint = h.checkpoint(Phase.UPLOAD_MAIN).copy(ackOffset=37)
        h.controller.inspect(); h.controller.awaitIdle()
        assertTrue(h.controller.presentation.value.hasCheckpoint)
        assertFalse(h.controller.presentation.value.imagesVerified)
        assertEquals(Phase.UPLOAD_MAIN, h.controller.presentation.value.phase)
        h.checkpoint = h.checkpoint(Phase.AWAIT_OPERATOR).copy(resetAcknowledged=true)
        h.operator = true; h.reportExists = true
        h.controller.inspect(); h.controller.awaitIdle()
        val ui = h.controller.presentation.value
        assertTrue(ui.imagesVerified); assertTrue(ui.resetAcknowledged)
        assertEquals(true, ui.operatorOnline); assertTrue(ui.reportAvailable)
        assertEquals(0, h.transports + h.saves)
        h.scope.cancel()
    }

    @Test fun failedEvidenceReadFailsClosedWhileRetainingSelectedDeviceAndReport() = runBlocking {
        val h = Harness(); h.corruptCheckpoint = true; h.reportExists = true
        h.controller.inspect(); h.controller.awaitIdle()
        val ui = h.controller.presentation.value
        assertTrue(ui.inspected); assertFalse(ui.loaded); assertFalse(ui.busy)
        assertNotNull(ui.packageSummary); assertTrue(ui.reportAvailable)
        assertFalse(ui.imagesVerified); assertFalse(ui.bluetoothVerified)
        assertTrue(h.controller.status.value.startsWith("Paused"))
        assertEquals(0, h.transports + h.saves)
        h.scope.cancel()
    }

    @Test fun probeVerificationIsBoundToPackageAndClearedOnFailureOrNewSelection() = runBlocking {
        val h = Harness()
        h.controller.probe(); h.controller.awaitIdle()
        assertTrue(h.controller.presentation.value.bluetoothVerified)
        assertTrue(h.controller.presentation.value.reportAvailable)
        val outcome = h.controller.status.value
        h.controller.inspect(); h.controller.awaitIdle()
        assertEquals(outcome, h.controller.status.value)
        assertTrue(h.controller.presentation.value.bluetoothVerified)
        h.connectAction = { error("Bluetooth failure") }
        h.controller.probe(); h.controller.awaitIdle()
        assertFalse(h.controller.presentation.value.bluetoothVerified)
        h.connectAction = {}; h.controller.probe(); h.controller.awaitIdle()
        h.nextSelection = h.pkg.copy(bundleDigest="a".repeat(64), manifest=h.pkg.manifest.copy(device=h.pkg.manifest.device.copy(bleAddress="AA:BB:CC:DD:EE:02")))
        h.controller.importDocument("second"); h.controller.awaitIdle()
        assertEquals("a".repeat(64), h.controller.presentation.value.packageSummary!!.digest)
        assertFalse(h.controller.presentation.value.bluetoothVerified)
        assertEquals(0, h.saves + h.uploads + h.resets)
        h.scope.cancel()
    }

    @Test fun activeOperationRemainsTypedAndInspectionCannotInterruptIt() = runBlocking {
        val h = Harness(); val entered=CompletableDeferred<Unit>(); val release=CompletableDeferred<Unit>()
        h.connectAction = { entered.complete(Unit); release.await() }
        h.controller.probe(); entered.await()
        assertTrue(h.controller.presentation.value.busy)
        assertEquals(SessionOperation.PROBE, h.controller.presentation.value.operation)
        val currentStatus = h.controller.status.value
        assertFalse(h.controller.inspect())
        assertEquals(currentStatus, h.controller.status.value)
        assertEquals(SessionOperation.PROBE, h.controller.presentation.value.operation)
        release.complete(Unit); h.controller.awaitIdle()
        assertFalse(h.controller.presentation.value.busy)
        assertEquals(SessionOperation.IDLE, h.controller.presentation.value.operation)
        h.scope.cancel()
    }

    @Test fun startingAReadOnlyProbeClearsSavedUploadProgressWhileConnecting() = runBlocking {
        val h=Harness()
        h.checkpoint=h.checkpoint(Phase.UPLOAD_MAIN).copy(ackOffset=h.pkg.main.size/2)
        h.controller.inspect();h.controller.awaitIdle()
        assertTrue(h.controller.presentation.value.progressPercent!! > 0)
        val entered=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>()
        h.connectAction={entered.complete(Unit);release.await()}
        h.controller.probe();entered.await()
        try {
            assertEquals(SessionOperation.PROBE,h.controller.presentation.value.operation)
            assertNull(h.controller.presentation.value.progressPercent)
            assertEquals(0,h.saves+h.uploads+h.resets)
        }finally{release.complete(Unit);h.controller.awaitIdle();h.scope.cancel()}
    }

    @Test fun foreignCheckpointNeverBecomesVerifiedPresentationEvidence() = runBlocking {
        val h = Harness(); h.checkpoint = h.checkpoint(Phase.AWAIT_OPERATOR).copy(bundleDigest="f".repeat(64), resetAcknowledged=true)
        h.controller.inspect(); h.controller.awaitIdle()
        assertFalse(h.controller.presentation.value.loaded)
        assertFalse(h.controller.presentation.value.imagesVerified)
        assertFalse(h.controller.presentation.value.resetAcknowledged)
        assertEquals(0, h.transports + h.connects + h.uploads + h.resets + h.saves)
        h.scope.cancel()
    }

    @Test fun updateAndOperatorCompletionRefreshDurableEvidence() = runBlocking {
        val h = Harness()
        h.controller.start(false); h.controller.awaitIdle()
        val ui = h.controller.presentation.value
        assertTrue(ui.hasCheckpoint); assertTrue(ui.imagesVerified); assertTrue(ui.resetAcknowledged)
        assertEquals(Phase.AWAIT_OPERATOR, ui.phase)
        assertTrue(ui.reportAvailable); assertNull(ui.operatorOnline)
        h.controller.confirmOperator(true); h.controller.awaitIdle()
        assertEquals(true, h.controller.presentation.value.operatorOnline)
        assertEquals(1, h.uploads); assertEquals(1, h.resets)
        h.scope.cancel()
    }
}
