package org.openvimar.updater

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import org.openvimar.updater.core.*
import java.io.File
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec

class SessionControllerTest {
    private class Harness(dispatcher: CoroutineDispatcher = Dispatchers.Unconfined) {
        val scope = CoroutineScope(SupervisorJob() + dispatcher)
        val pkg = PackageValidator.validate(PackageReader.read(File("../test-fixtures/synthetic-update.zip").inputStream()),
            KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(File("../test-fixtures/synthetic-public.der").readBytes())), "0.1.0")
        var selected = pkg
        var onSelection: () -> Unit = {}
        var checkpoint: Checkpoint? = null
        var corruptReport = false
        var connects = 0
        var uploads = 0
        var resets = 0
        var closes = 0
        var saves = 0
        var reported = ""
        var selections = 0
        var permitted = true
        var loadPackage: suspend () -> Unit = {}
        var connectAction: suspend () -> Unit = {}
        var importEntered = CompletableDeferred<Unit>()
        var importRelease = CompletableDeferred<Unit>()
        var uploadEntered = CompletableDeferred<Unit>()
        var uploadRelease = CompletableDeferred<Unit>()
        var primary: RemoteImage? = RemoteImage(pkg.manifest.allowedSourceSignedHashes.first(), false, true)
        val store = object : SessionStore {
            override suspend fun load(bundleDigest: String, address: String) = checkpoint
            override suspend fun save(checkpoint: Checkpoint) { saves++; this@Harness.checkpoint = checkpoint }
        }
        val transport = object : BleTransport {
            override suspend fun connect(address: String) { check(permitted); connects++; connectAction() }
            override suspend fun images() = RemoteImages(primary, RemoteImage(pkg.manifest.targetRecoverySignedHash, true, true))
            override suspend fun upload(data: ByteArray, onAck: suspend (Int) -> Unit) {
                uploads++; uploadEntered.complete(Unit); uploadRelease.await(); check(permitted)
                onAck(data.size); primary = RemoteImage(pkg.manifest.main.signedRegionSha256, false, true)
            }
            override suspend fun reset(): ResetAck { resets++; return ResetAck.ACKNOWLEDGED }
            override suspend fun close() { closes++ }
        }
        val controller = SessionController(scope, store, { loadPackage(); selected }, {
            if (corruptReport) error("corrupt report") else null
        }, { _, checkActive, commit ->
            importEntered.complete(Unit)
            withContext(NonCancellable) { importRelease.await() }
            checkActive()
            commit { selections++; onSelection() }
        }, { transport }, { _, _, outcome -> reported = outcome }, { byteArrayOf() }, { permitted })
    }

    @Test fun bluetoothProbeReadsKnownImagesWithoutChangingCheckpointOrSendingWrites() = runBlocking {
        val h = Harness()
        val previous = Checkpoint(bundleDigest=h.pkg.bundleDigest, bleAddress=h.pkg.manifest.device.bleAddress,
            phase=Phase.UPLOAD_MAIN, ackOffset=37)
        h.checkpoint = previous
        assertTrue(h.controller.probe())
        h.controller.awaitIdle()
        assertEquals(1, h.connects)
        assertEquals(1, h.closes)
        assertEquals(0, h.uploads)
        assertEquals(0, h.resets)
        assertEquals(0, h.saves)
        assertEquals(h.primary?.hash, h.controller.presentation.value.observedMainHash)
        assertSame(previous, h.checkpoint)
        assertTrue(h.controller.status.value.contains("Bluetooth check succeeded"))
        assertEquals(h.controller.status.value, h.reported)
        h.scope.cancel()
    }

    @Test fun bluetoothProbeUnknownImageReportsIncompatibilityWithoutMutation() = runBlocking {
        val h = Harness()
        h.primary = RemoteImage("f".repeat(64), false, true)
        assertTrue(h.controller.probe())
        h.controller.awaitIdle()
        assertTrue(h.controller.status.value.contains("does not match"))
        assertEquals(h.controller.status.value, h.reported)
        assertEquals(0, h.uploads + h.resets + h.saves)
        assertEquals(1, h.closes)
        h.scope.cancel()
    }

    @Test fun bluetoothProbeFailureIsExportableAndDoesNotPreventAnotherProbe() = runBlocking {
        val h = Harness()
        h.connectAction = { error("Abbinamento Android rifiutato") }
        assertTrue(h.controller.probe())
        h.controller.awaitIdle()
        assertTrue(h.reported.contains("Abbinamento Android rifiutato"))
        assertFalse(h.controller.busy.value)
        assertEquals(0, h.uploads + h.resets + h.saves)
        h.connectAction = {}
        assertTrue(h.controller.probe())
        h.controller.awaitIdle()
        assertTrue(h.reported.contains("Bluetooth check succeeded"))
        h.scope.cancel()
    }

    @Test fun acceptedUpdatePublishesPreparationBeforeQueuedPackageLoad() = runBlocking {
        val dispatcher = PausedDispatcher()
        val h = Harness(dispatcher)
        assertTrue(h.controller.start(false))
        assertTrue(h.controller.status.value.contains("Preparing"))
        assertEquals(0, h.connects)
        h.controller.stop()
        dispatcher.drain()
        h.scope.cancel()
    }

    @Test fun suspendedConnectPublishesProgressThenFailureCause() = runBlocking {
        val h = Harness()
        val entered = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        h.connectAction = { entered.complete(Unit); release.await(); error("Dispositivo non raggiungibile") }
        assertTrue(h.controller.start(false))
        entered.await()
        assertTrue(h.controller.status.value.contains("Connecting"))
        assertTrue(h.controller.status.value.contains("pairing"))
        release.complete(Unit)
        h.controller.awaitIdle()
        assertTrue(h.controller.status.value.contains("Dispositivo non raggiungibile"))
        assertTrue(h.controller.status.value.startsWith("Paused"))
        h.scope.cancel()
    }

    @Test fun busyImportRejectsUpdateWithVisibleExplanation() = runBlocking {
        val h = Harness()
        h.controller.importDocument("provider")
        h.importEntered.await()
        assertFalse(h.controller.start(false))
        assertTrue(h.controller.status.value.contains("Wait"))
        assertTrue(h.controller.status.value.contains("import"))
        assertEquals(0, h.connects)
        h.controller.stop()
        h.importRelease.complete(Unit)
        h.controller.awaitIdle()
        h.scope.cancel()
    }

    @Test fun activeRotationAndRebindDoNotDuplicateUpload() = runBlocking {
        val h = Harness()
        assertTrue(h.controller.start(false))
        h.uploadEntered.await()
        val rebound = h.controller
        assertFalse(rebound.start(false))
        assertEquals(1, h.connects)
        assertEquals(1, h.uploads)
        h.uploadRelease.complete(Unit)
        h.controller.awaitIdle()
        assertEquals(1, h.resets)
    }

    @Test fun slowImportSurvivesOwnerRebindAndStopPreventsLateSelection() = runBlocking {
        val h = Harness()
        assertTrue(h.controller.importDocument("provider"))
        h.importEntered.await()
        val replacementServiceOwner = h.controller
        assertFalse(replacementServiceOwner.start(false))
        assertFalse(replacementServiceOwner.importDocument("second"))
        replacementServiceOwner.stop()
        assertFalse(replacementServiceOwner.start(false))
        h.importRelease.complete(Unit)
        h.controller.awaitIdle()
        assertEquals(0, h.selections)
        assertTrue(h.controller.importDocument("retry"))
        h.controller.awaitIdle()
        assertEquals(1, h.selections)
    }

    @Test fun staleResetDialogCannotAuthorizeAfterImport() = runBlocking {
        val h = Harness()
        h.primary = RemoteImage(h.pkg.manifest.main.signedRegionSha256, false, true)
        h.checkpoint = Checkpoint(bundleDigest = h.pkg.bundleDigest, bleAddress = h.pkg.manifest.device.bleAddress,
            phase = Phase.FINAL_RESET_INTENT)
        val offer = h.controller.prepareResume()
        assertTrue(offer.needsConfirmation)
        h.onSelection = {
            h.selected = h.pkg.copy(bundleDigest = "b".repeat(64), manifest = h.pkg.manifest.copy(
                device = h.pkg.manifest.device.copy(bleAddress = "AA:BB:CC:DD:EE:02")))
            h.checkpoint = h.checkpoint!!.copy(bundleDigest = h.selected.bundleDigest, bleAddress = h.selected.manifest.device.bleAddress)
        }
        h.importRelease.complete(Unit)
        assertTrue(h.controller.importDocument("different-selection"))
        h.controller.awaitIdle()
        assertTrue(h.controller.start(true, offer.id, true))
        h.controller.awaitIdle()
        assertEquals(0, h.connects)
        assertEquals(0, h.resets)
        val fresh = h.controller.prepareResume()
        h.controller.start(true, fresh.id, true)
        h.controller.awaitIdle()
        assertEquals(1, h.resets)
    }

    @Test fun corruptReportReleasesGateForRetryAndReimport() = runBlocking {
        val h = Harness()
        h.corruptReport = true
        h.controller.start(false)
        h.controller.awaitIdle()
        assertFalse(h.controller.busy.value)
        assertEquals(0, h.connects)
        h.corruptReport = false
        h.importRelease.complete(Unit)
        assertTrue(h.controller.importDocument("retry"))
        h.controller.awaitIdle()
        assertTrue(h.controller.start(false))
        h.uploadRelease.complete(Unit)
        h.controller.awaitIdle()
        assertEquals(1, h.uploads)
    }

    @Test fun processReopenDoesNotConnectAndRequiresResumeOffer() = runBlocking {
        val h = Harness()
        h.checkpoint = Checkpoint(bundleDigest = h.pkg.bundleDigest, bleAddress = h.pkg.manifest.device.bleAddress, phase = Phase.UPLOAD_MAIN)
        assertEquals(0, h.connects)
        h.controller.start(false)
        h.controller.awaitIdle()
        assertEquals(0, h.connects)
        val offer = h.controller.prepareResume()
        h.controller.start(true, offer.id)
        h.uploadRelease.complete(Unit)
        h.controller.awaitIdle()
        assertEquals(1, h.uploads)
    }

    @Test fun permissionRevokedDuringUploadPausesWithoutResetAndGateReleases() = runBlocking {
        val h = Harness()
        h.controller.start(false)
        h.uploadEntered.await()
        h.permitted = false
        h.uploadRelease.complete(Unit)
        h.controller.awaitIdle()
        assertEquals(0, h.resets)
        assertFalse(h.controller.busy.value)
    }
    private class PausedDispatcher : CoroutineDispatcher() {
        private val queued = java.util.ArrayDeque<Runnable>()
        override fun dispatch(context: kotlin.coroutines.CoroutineContext, block: Runnable) { queued.add(block) }
        fun drain() { while (queued.isNotEmpty()) queued.removeFirst().run() }
    }

    @Test fun stopBeforePrepareOrExportBodyCompletesWaitingCallerAndReleasesAdmission() = runBlocking {
        for (prepare in listOf(true, false)) {
            val dispatcher = PausedDispatcher()
            val h = Harness(dispatcher)
            val caller = async(start = CoroutineStart.UNDISPATCHED) {
                runCatching { if (prepare) h.controller.prepareResume() else h.controller.report() }
            }
            try {
                assertTrue(h.controller.busy.value)
                h.controller.stop()
                dispatcher.drain()
                yield()
                assertTrue("Stopped $prepare caller must not remain suspended", caller.isCompleted)
                assertTrue(caller.await().isFailure)
                assertFalse(h.controller.busy.value)
                assertEquals(0, h.connects)
                assertEquals(0, h.resets)
                h.importRelease.complete(Unit)
                assertTrue(h.controller.importDocument("after-stop"))
                dispatcher.drain()
                assertFalse(h.controller.busy.value)
            } finally { caller.cancelAndJoin(); h.scope.cancel() }
        }
    }
}
