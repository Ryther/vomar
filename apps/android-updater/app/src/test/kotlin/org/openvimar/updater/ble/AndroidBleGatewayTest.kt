package org.openvimar.updater.ble

import android.bluetooth.BluetoothDevice
import android.content.Context
import java.security.MessageDigest
import kotlinx.coroutines.*
import no.nordicsemi.android.mcumgr.*
import no.nordicsemi.android.mcumgr.ble.McuMgrBleTransport
import no.nordicsemi.android.mcumgr.ble.exception.McuMgrDisconnectedException
import no.nordicsemi.android.mcumgr.exception.McuMgrException
import no.nordicsemi.android.mcumgr.exception.McuMgrTimeoutException
import no.nordicsemi.android.mcumgr.managers.DefaultManager
import no.nordicsemi.android.mcumgr.managers.ImageManager
import no.nordicsemi.android.mcumgr.response.McuMgrResponse
import no.nordicsemi.android.mcumgr.util.CBOR
import org.junit.Assert.*
import org.junit.Test
import org.mockito.Mockito.*
import org.openvimar.updater.core.ResetAck

/** Real gateway and Nordic managers; only Android handles and the SMP wire are synthetic. */
class AndroidBleGatewayTest {
    private val address = "AA:BB:CC:DD:EE:FF"
    private enum class Command { IMAGES, CHUNK, RESET }

    private class Pending(
        val bytes: ByteArray,
        val reply: (Map<String, Any>) -> Unit,
        val reject: (McuMgrException) -> Unit
    ) {
        fun payload(): Map<*, *> = CBOR.toObject(bytes.copyOfRange(8, bytes.size), Map::class.java)
        fun assertCommand(operation: Int, group: Int, command: Int) {
            assertEquals(operation, bytes[0].toInt() and 7)
            assertEquals(group, ((bytes[4].toInt() and 255) shl 8) or (bytes[5].toInt() and 255))
            assertEquals(command, bytes[7].toInt() and 255)
        }
    }

    private class Wire : McuMgrTransport {
        val requests = mutableListOf<Pending>()
        override fun getScheme() = McuMgrScheme.BLE
        override fun <T : McuMgrResponse> send(bytes: ByteArray, timeout: Long, type: Class<T>): T =
            error("The gateway must use asynchronous SMP requests")
        override fun <T : McuMgrResponse> send(bytes: ByteArray, timeout: Long, type: Class<T>, callback: McuMgrCallback<T>) {
            requests += Pending(bytes.copyOf(), { payload ->
                val body = CBOR.toBytes(payload)
                val header = bytes.copyOfRange(0, 8)
                header[0] = (header[0].toInt() or 1).toByte()
                header[2] = (body.size shr 8).toByte()
                header[3] = body.size.toByte()
                callback.onResponse(McuMgrResponse.buildResponse(McuMgrScheme.BLE, header + body, type))
            }, callback::onError)
        }
        override fun connect(callback: McuMgrTransport.ConnectionCallback?) = error("No implicit connection")
        override fun changeMode(name: String, callback: McuMgrTransport.ModeChangeCallback?): Boolean = error("No implicit peer change")
        override fun release() = error("Release belongs to the captured gateway owner")
        override fun addObserver(observer: McuMgrTransport.ConnectionObserver) {}
        override fun removeObserver(observer: McuMgrTransport.ConnectionObserver) {}
    }

    // AGP supplies mockable Android handles. The test-only reflection member accessor
    // keeps Mockito subclass mocks from attaching an agent on Java 21.
    private inner class Harness {
        val context = mock(Context::class.java)
        val device = mock(BluetoothDevice::class.java)
        val readyTransport = mock(McuMgrBleTransport::class.java)
        val gateway: AndroidBleGateway
        var releases = 0
        var wire = Wire()
            private set

        init {
            `when`(context.applicationContext).thenReturn(context)
            `when`(device.bondState).thenReturn(BluetoothDevice.BOND_BONDED)
            gateway = AndroidBleGateway(context, address)
            installSession()
            verifyNoInteractions(readyTransport)
            assertTrue(wire.requests.isEmpty())
        }
        fun field(name: String, value: Any?) {
            AndroidBleGateway::class.java.getDeclaredField(name).apply { isAccessible = true }.set(gateway, value)
        }
        fun installSession() {
            wire = Wire()
            field("device", device)
            field("transport", readyTransport)
            field("owner", OwnedSubmission { releases++ })
            field("imageManager", ImageManager(wire).also { it.setUploadMtu(244) })
            field("osManager", DefaultManager(wire))
        }
        suspend fun call(command: Command) {
            when (command) {
                Command.IMAGES -> gateway.images()
                Command.CHUNK -> gateway.chunk(byteArrayOf(1, 2, 3), 0, 0)
                Command.RESET -> gateway.reset()
            }
        }
    }

    private suspend fun fails(type: Class<out Throwable>, action: suspend () -> Unit) {
        val failure = runCatching { action() }.exceptionOrNull()
        assertTrue("Expected ${type.simpleName}, got $failure", type.isInstance(failure))
    }

    @Test(timeout = 10_000) fun androidHandleMocksDoNotAttachAByteBuddyAgentOnTheHostJvm() {
        val h = Harness()
        assertThrows(IllegalStateException::class.java) { net.bytebuddy.agent.ByteBuddyAgent.getInstrumentation() }
        h.gateway.close()
    }

    @Test(timeout = 10_000) fun imageListUsesActualNordicReadAndPreservesOptionalSlotObservations() = runBlocking {
        val h = Harness()
        val read = async(start = CoroutineStart.UNDISPATCHED) { h.gateway.images() }
        h.wire.requests.single().apply {
            assertCommand(0, 1, 0)
            assertTrue(payload().isEmpty())
            reply(mapOf("images" to listOf(
                mapOf("image" to 0, "slot" to 1, "hash" to byteArrayOf(0xff.toByte(), 1), "active" to true, "bootable" to true, "version" to "1.2.3"),
                mapOf("image" to 0, "slot" to 0, "active" to false, "bootable" to false)
            )))
        }
        assertEquals(listOf(Slot(0, 1, "ff01", true, true, "1.2.3"), Slot(0, 0, null, false, false)), read.await())
        verifyNoInteractions(h.readyTransport)
        h.gateway.close()
        assertEquals(1, h.releases)
    }

    @Test(timeout = 10_000) fun chunkUsesActualNordicPayloadAndReturnsOnlyTheSingleReportedAcknowledgement() = runBlocking {
        val h = Harness()
        val data = byteArrayOf(1, 2, 3, 4, 5, 6)
        val first = async(start = CoroutineStart.UNDISPATCHED) { h.gateway.chunk(data, 0, 0) }
        h.wire.requests.single().apply {
            assertCommand(2, 1, 1)
            val payload = payload()
            assertEquals(setOf("data", "off", "len", "sha"), payload.keys)
            assertEquals(0, payload["off"])
            assertEquals(data.size, payload["len"])
            assertArrayEquals(data, payload["data"] as ByteArray)
            assertArrayEquals(MessageDigest.getInstance("SHA-256").digest(data), payload["sha"] as ByteArray)
            reply(mapOf("off" to 4, "match" to true))
        }
        assertEquals(Chunk(4, true), first.await())
        val continuation = async(start = CoroutineStart.UNDISPATCHED) { h.gateway.chunk(data, 4, 0) }
        h.wire.requests.last().apply {
            assertCommand(2, 1, 1)
            assertEquals(setOf("data", "off"), payload().keys)
            assertArrayEquals(byteArrayOf(5, 6), payload()["data"] as ByteArray)
            reply(mapOf("off" to 6, "match" to false))
        }
        assertEquals(Chunk(6, false), continuation.await())
        assertEquals(2, h.wire.requests.size)
        h.gateway.close()
    }

    @Test(timeout = 10_000) fun resetUsesActualNordicNormalBootRequestWithoutExtraCommands() = runBlocking {
        val h = Harness()
        val reset = async(start = CoroutineStart.UNDISPATCHED) { h.gateway.reset() }
        h.wire.requests.single().apply {
            assertCommand(2, 0, 5)
            assertTrue(payload().isEmpty())
            reply(emptyMap())
        }
        reset.await()
        assertEquals(1, h.wire.requests.size)
        h.gateway.close()
    }

    @Test(timeout = 10_000) fun everyGatewayCommandRejectsMissingManagerBeforeSending() = runBlocking {
        for (command in Command.entries) {
            val h = Harness()
            h.field(if (command == Command.RESET) "osManager" else "imageManager", null)
            fails(IllegalStateException::class.java) { h.call(command) }
            assertTrue(h.wire.requests.isEmpty())
            h.gateway.close()
        }
    }

    @Test(timeout = 10_000) fun everyGatewayCommandRequiresTheExistingBondAndLiveTransport() = runBlocking {
        for (command in Command.entries) {
            val h = Harness()
            `when`(h.device.bondState).thenReturn(BluetoothDevice.BOND_NONE)
            fails(IllegalStateException::class.java) { h.call(command) }
            `when`(h.device.bondState).thenReturn(BluetoothDevice.BOND_BONDED)
            h.field("transport", null)
            fails(IllegalStateException::class.java) { h.call(command) }
            assertTrue(h.wire.requests.isEmpty())
            h.gateway.close()
        }
    }

    @Test(timeout = 10_000) fun missingImageRecordsAndRejectedCallbacksCannotBecomeSuccessfulResults() = runBlocking {
        supervisorScope {
            val h = Harness()
            val read = async(start = CoroutineStart.UNDISPATCHED) { h.gateway.images() }
            h.wire.requests.single().reply(emptyMap())
            fails(IllegalStateException::class.java) { read.await() }
            h.gateway.close()
            for (command in Command.entries) {
                val rejected = Harness()
                val operation = async(start = CoroutineStart.UNDISPATCHED) { rejected.call(command) }
                rejected.wire.requests.single().reply(mapOf("rc" to 8))
                fails(IllegalStateException::class.java) { operation.await() }
                assertEquals(1, rejected.wire.requests.size)
                rejected.gateway.close()
            }
        }
    }

    @Test(timeout = 10_000) fun realResetTimeoutAndDisconnectRemainAmbiguousWithoutRetry() = runBlocking {
        for (failure in listOf(McuMgrTimeoutException(), McuMgrDisconnectedException())) {
            val h = Harness()
            val reset = async(start = CoroutineStart.UNDISPATCHED) { NordicBleTransport(address, h.gateway).reset() }
            h.wire.requests.single().reject(failure)
            assertEquals(ResetAck.LOST, reset.await())
            assertEquals(1, h.wire.requests.size)
            assertEquals(0, h.releases)
            h.gateway.close()
            assertEquals(1, h.releases)
        }
    }

    @Test(timeout = 10_000) fun cancellationReleasesOnlyItsCapturedOwnerAndOldCallbacksCannotCompleteTheNextSession() = runBlocking {
        val h = Harness()
        val upload = async(start = CoroutineStart.UNDISPATCHED) { h.gateway.chunk(byteArrayOf(1, 2), 0, 0) }
        val stale = h.wire.requests.single()
        upload.cancelAndJoin()
        assertEquals(1, h.releases)
        h.gateway.close()
        assertEquals(1, h.releases)
        h.installSession()
        val next = async(start = CoroutineStart.UNDISPATCHED) { h.gateway.images() }
        stale.reply(mapOf("off" to 2, "match" to true))
        stale.reject(McuMgrDisconnectedException())
        assertFalse(next.isCompleted)
        assertEquals(1, h.releases)
        h.wire.requests.single().reply(mapOf("images" to emptyList<Any>()))
        assertTrue(next.await().isEmpty())
        h.gateway.close()
        assertEquals(2, h.releases)
    }

    @Test(timeout = 10_000) fun staleGenerationCannotCompleteRequestsOrReleaseTheReplacementOwner() = runBlocking {
        val h = Harness()
        val old = async(start = CoroutineStart.UNDISPATCHED) { h.gateway.images() }
        val stale = h.wire.requests.single()
        h.gateway.close()
        assertEquals(1, h.releases)
        h.installSession()
        val replacement = async(start = CoroutineStart.UNDISPATCHED) { h.gateway.images() }
        stale.reply(mapOf("images" to emptyList<Any>()))
        stale.reject(McuMgrDisconnectedException())
        assertFalse(old.isCompleted)
        assertFalse(replacement.isCompleted)
        old.cancelAndJoin()
        assertEquals(1, h.releases)
        h.wire.requests.single().reply(mapOf("images" to emptyList<Any>()))
        assertTrue(replacement.await().isEmpty())
        h.gateway.close()
        assertEquals(2, h.releases)
    }

}
