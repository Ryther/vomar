package org.openvimar.updater

import org.junit.Assert.*
import org.junit.Test
import java.io.IOException

class DkJlinkReadOnlyTest {
    private class Channel(vararg val replies: ByteArray) : DkBulkChannel {
        val commands = mutableListOf<Int>()
        var index = 0
        override fun write(bytes: ByteArray): Int {
            assertEquals(1, bytes.size)
            commands += bytes.single().toInt() and 255
            return bytes.size
        }
        override fun read(maxBytes: Int): ByteArray = replies[index++].also {
            assertTrue(it.size <= maxBytes)
        }
    }

    @Test fun readsVersionAndReferenceVoltageUsingOnlyTwoDiagnosticCommands() {
        val channel = Channel(byteArrayOf(5), byteArrayOf(0), "JLink".toByteArray(),
            byteArrayOf(0xe4.toByte(), 0x0c), byteArrayOf(1, 0, 1, 0, 1, 1))
        val result = DkJlinkReadOnly.probe(channel)
        assertEquals("JLink", result.firmware)
        assertEquals(3300, result.targetMillivolts)
        assertEquals(listOf(1, 7), channel.commands)
    }

    @Test fun zeroVoltageAndMissingFirmwareRemainObservationsNotSwdSuccess() {
        val channel = Channel(byteArrayOf(0, 0), ByteArray(8))
        val result = DkJlinkReadOnly.probe(channel)
        assertEquals("Not reported", result.firmware)
        assertEquals(0, result.targetMillivolts)
        assertEquals(listOf(1, 7), channel.commands)
    }

    @Test fun rejectsUnboundedVersionBeforeAnotherCommand() {
        val channel = Channel(byteArrayOf(0xff.toByte(), 0x7f))
        try { DkJlinkReadOnly.probe(channel); fail("Oversized version accepted") }
        catch (_: IOException) { assertEquals(listOf(1), channel.commands) }
    }

    @Test fun stopsOnTruncatedTransferInsteadOfReportingAWorkingDk() {
        val channel = Channel(byteArrayOf(5, 0), byteArrayOf())
        try { DkJlinkReadOnly.probe(channel); fail("Truncated reply accepted") }
        catch (_: IOException) { assertEquals(listOf(1), channel.commands) }
    }
}
