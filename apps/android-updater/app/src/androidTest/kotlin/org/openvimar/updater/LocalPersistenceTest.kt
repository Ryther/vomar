package org.openvimar.updater

import android.test.InstrumentationTestCase
import kotlinx.coroutines.runBlocking
import org.openvimar.updater.core.*
import java.io.File
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec

/** Platform source only: compile does not establish emulator, lifecycle, BLE or pairing behavior. */
@Suppress("DEPRECATION")
class LocalPersistenceTest : InstrumentationTestCase() {
    private fun isolated(): android.content.Context = object : android.content.ContextWrapper(instrumentation.targetContext) {
        private val directory = File(super.getFilesDir(), "instrumentation-${System.nanoTime()}").apply { mkdirs() }
        override fun getFilesDir(): File = directory
    }

    fun testPrivateCopySurvivesProviderDisappearance() {
        val context = isolated()
        val assets = instrumentation.context.assets
        val key = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(assets.open("synthetic-public.der").use { it.readBytes() }))
        val repository = DocumentRepository(context, key)
        val imported = assets.open("synthetic-update.zip").use { repository.importStream(it) }
        // The provider stream has closed; reopen uses only the private immutable ZIP.
        assertEquals(imported.bundleDigest, DocumentRepository(context, key).current()!!.bundleDigest)
        assertTrue(SessionFiles(context.filesDir).bundle(imported.bundleDigest).length() > 0)
    }

    fun testAtomicCheckpointReadbackAndMismatch() = runBlocking {
        val context = isolated()
        val store = AndroidSessionStore(context.filesDir)
        val checkpoint = Checkpoint(bundleDigest = "a".repeat(64), bleAddress = "AA:BB:CC:DD:EE:FF", phase = Phase.UPLOAD_MAIN)
        val identity = SessionFiles.Identity(checkpoint.bundleDigest, checkpoint.bleAddress)
        SessionFiles(context.filesDir).select(identity)
        store.save(checkpoint)
        assertEquals(checkpoint, AndroidSessionStore(context.filesDir).load(checkpoint.bundleDigest, checkpoint.bleAddress))
        assertNull(store.load("b".repeat(64), checkpoint.bleAddress))
        SessionFiles(context.filesDir).checkpoint(identity).writeText("broken")
        try { store.read(); fail("Corruption must reject") } catch (_: org.json.JSONException) { }
    }

    fun testFakeTransportDoesNotAutoResumeAfterReopen() = runBlocking {
        val context = isolated()
        val assets = instrumentation.context.assets
        val key = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(assets.open("synthetic-public.der").use { it.readBytes() }))
        val pkg = DocumentRepository(context, key).importStream(assets.open("synthetic-update.zip"))
        val store = AndroidSessionStore(context.filesDir)
        store.save(Checkpoint(bundleDigest = pkg.bundleDigest, bleAddress = pkg.manifest.device.bleAddress, phase = Phase.UPLOAD_MAIN))
        var operations = 0
        val fake = object : BleTransport {
            override suspend fun connect(address: String) { operations++ }
            override suspend fun images(): RemoteImages = error("No action authorized")
            override suspend fun upload(data: ByteArray, onAck: suspend (Int) -> Unit) { operations++ }
            override suspend fun reset(): ResetAck { operations++; return ResetAck.LOST }
            override suspend fun close() { }
        }
        val reopened = SessionPolicy(restored = AndroidSessionStore(context.filesDir).read() != null)
        if (reopened.begin(false, false)) UpdateCoordinator().run(pkg, fake, store) { }
        assertEquals(0, operations)
    }
    fun testNewDeviceAndReimportOldPartialPreservesAuthority() = runBlocking {
        val context = isolated()
        val assets = instrumentation.context.assets
        val key = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(assets.open("synthetic-public.der").use { it.readBytes() }))
        val repository = DocumentRepository(context, key)
        val first = repository.importStream(assets.open("synthetic-update.zip"))
        val store = AndroidSessionStore(context.filesDir)
        val partial = Checkpoint(bundleDigest = first.bundleDigest, bleAddress = first.manifest.device.bleAddress,
            phase = Phase.UPLOAD_MAIN, ackOffset = 64)
        store.save(partial)
        val second = repository.importStream(assets.open("synthetic-second.zip"))
        assertFalse(first.manifest.device.bleAddress == second.manifest.device.bleAddress)
        assertNull(store.read())
        assertEquals(partial, store.load(first.bundleDigest, first.manifest.device.bleAddress))
        repository.importStream(assets.open("synthetic-update.zip"))
        assertEquals(partial, store.read())
        assertTrue(SessionFiles(context.filesDir).bundle(second.bundleDigest).exists())
        assertFalse(SessionPolicy(restored = store.read() != null).begin(false, false))
    }
}
