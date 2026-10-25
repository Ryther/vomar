package org.openvimar.updater

import org.junit.Assert.*
import org.junit.Test
import java.io.IOException

class DkSwdReadOnlyTest {
    private fun failure(action: () -> Unit): String {
        try { action(); fail("Operation should stop") } catch (error: IOException) { return error.message.orEmpty() }
        return ""
    }

    @Test fun buffersUsbPacketsWithoutLosingCoalescedPayloadOrStatus() {
        val requested = mutableListOf<Int>()
        val raw = object : DkBulkChannel {
            override fun write(bytes: ByteArray) = bytes.size
            override fun read(maxBytes: Int): ByteArray {
                requested += maxBytes
                return byteArrayOf(3, 0, 65, 66, 67, 0)
            }
        }
        val buffered = DkSwdBufferedChannel(raw)
        assertArrayEquals(byteArrayOf(3, 0), buffered.read(2))
        assertArrayEquals(byteArrayOf(65, 66, 67), buffered.read(3))
        assertArrayEquals(byteArrayOf(0), buffered.read(1))
        assertEquals(listOf(2048), requested)
    }

    @Test fun derivesRequestParityAndDecodesJlinkSampledDpidr() {
        val device = TargetModel()
        val port = DkSwdJlinkSession(device)
        assertEquals(0x2ba01477L, port.readDp(0))
        assertEquals(0xa5, device.requests.single())
        assertEquals(54, device.bitCounts.single())
    }

    @Test fun rejectsBadReadParityWithoutReturningIdentity() {
        val device = TargetModel().apply { corruptParity = true }
        assertTrue(failure { DkSwdJlinkSession(device).readDp(0) }.contains("parity"))
    }

    @Test fun retriesWaitWithABoundAndStopsOnFaultOrInvalidAck() {
        val waiting = TargetModel().apply { waits = 2 }
        assertEquals(0x2ba01477L, DkSwdJlinkSession(waiting).readDp(0))
        assertEquals(3, waiting.requests.size)
        val exhausted = TargetModel().apply { waits = 100 }
        assertTrue(failure { DkSwdJlinkSession(exhausted).readDp(0) }.contains("WAIT"))
        assertEquals(8, exhausted.requests.size)
        for (ack in listOf(4, 0, 7)) {
            val device = TargetModel().apply { forcedAck = ack }
            assertTrue(failure { DkSwdJlinkSession(device).readDp(0) }.isNotEmpty())
            assertEquals(1, device.requests.size)
        }
    }

    @Test fun writeWaitNeverClocksDataUntilAcknowledgedAndEncodesWriteParity() {
        val device = TargetModel()
        val session=DkSwdJlinkSession(device)
        session.readDp(4) // Establish ORUN=0 before injecting this write WAIT.
        device.waits=1
        session.writeDp(8, 0xf0)
        assertEquals(listOf(54, 12, 9, 12, 42), device.bitCounts)
        assertEquals(listOf(Triple(false, 8, 0xf0L)), device.debugWrites)
        assertTrue(device.writeParityChecked)
    }

    @Test fun stopsOnWriteFaultWithoutClockingADataPhase() {
        val device = TargetModel()
        val session=DkSwdJlinkSession(device)
        session.readDp(4)
        device.forcedAck=4
        assertTrue(failure { session.writeDp(8, 0) }.contains("FAULT"))
        assertEquals(listOf(54, 12, 9), device.bitCounts)
        assertTrue(device.debugWrites.isEmpty())
    }

    @Test fun stopsOnProbeStatusTruncationAndGlobalDeadline() {
        val badStatus = TargetModel().apply { probeStatus = 6 }
        assertTrue(failure { DkSwdJlinkSession(badStatus).readDp(0) }.contains("status"))
        val empty = object : DkBulkChannel {
            override fun write(bytes: ByteArray) = bytes.size
            override fun read(maxBytes: Int) = byteArrayOf()
        }
        assertTrue(failure { DkSwdJlinkSession(empty).readDp(0) }.contains("reply"))
        var clock = 0L
        val device = TargetModel()
        val session = DkSwdJlinkSession(device, now = { clock }, timeoutMillis = 1)
        clock = 2_000_000
        assertTrue(failure { session.readDp(0) }.contains("timed out"))
        assertTrue(device.requests.isEmpty())
    }

    @Test fun identityReadsOnlyThreeFicrWordsAndNeverWritesTargetMemory() {
        val device = TargetModel()
        val observed = linkedMapOf<String, Any>()
        DkSwdReadOnly.probe(device) { key, value -> observed[key] = value }
        assertEquals("0x00052840", observed["part"])
        assertEquals(listOf("0x12345678", "0xabcdef01"), observed["uid"])
        assertEquals(listOf(0x10000100L, 0x10000060L, 0x10000064L), device.memoryReads)
        assertFalse(observed["commercialModelVerified"] as Boolean)
        assertTrue(device.debugWrites.all { (ap, address, value) ->
            if (ap) address == 0 || address == 4
            else address == 0 && value == 0x1eL || address == 4 && value == 0x50000001L || address == 8 && value in listOf(0L, 0xf0L)
        })
        assertTrue(device.commands.all { it in listOf(0xe8, 0xc7, 0x05, 0xcf) })
    }

    @Test fun rejectsUnsupportedProbeTargetAndPowerUpTimeoutBeforeFicrRead() {
        val noCapability = TargetModel().apply { selectSupported = false }
        assertTrue(failure { DkSwdReadOnly.probe(noCapability) }.contains("interface selection"))
        assertEquals(listOf(0xe8), noCapability.commands)
        val noSwd = TargetModel().apply { swdSupported = false }
        assertTrue(failure { DkSwdReadOnly.probe(noSwd) }.contains("SWD"))
        assertTrue(noSwd.bitCounts.isEmpty())
        val unknown = TargetModel().apply { dpidr = 0x6ba02477 }
        assertTrue(failure { DkSwdReadOnly.probe(unknown) }.contains("DPIDR"))
        assertTrue(unknown.debugWrites.isEmpty())
        val asleep = TargetModel().apply { powerAcknowledged = false }
        assertTrue(failure { DkSwdReadOnly.probe(asleep) }.contains("power"))
        assertTrue(asleep.memoryReads.isEmpty())
    }

    @Test fun wrongChipAndAccessErrorsPreservePartialEvidence() {
        val device = TargetModel().apply { part = 0x12345 }
        val observed = linkedMapOf<String, Any>()
        assertTrue(failure { DkSwdReadOnly.probe(device) { key, value -> observed[key] = value } }.contains("nRF52840"))
        assertEquals("0x2ba01477", observed["dpidr"])
        assertEquals("0x00012345", observed["part"])
        assertEquals(listOf(0x10000100L), device.memoryReads)
        val disabled = TargetModel().apply { memoryEnabled = false }
        assertTrue(failure { DkSwdReadOnly.probe(disabled) }.contains("disabled"))
        assertTrue(disabled.memoryReads.isEmpty())
        val wrongAp = TargetModel().apply { apId = 0x24770012 }
        assertTrue(failure { DkSwdReadOnly.probe(wrongAp) }.contains("AHB"))
        assertTrue(wrongAp.memoryReads.isEmpty())
    }

    @Test fun rejectsShortUsbWritesAndTimeoutAfterAReplyArrives() {
        val short = object : DkBulkChannel {
            override fun write(bytes: ByteArray) = bytes.size-1
            override fun read(maxBytes: Int): ByteArray = throw AssertionError("Must stop before reading")
        }
        assertTrue(failure { DkSwdJlinkSession(short).readDp(0) }.contains("command"))
        val device = TargetModel()
        var clock = 0L
        val late = object : DkBulkChannel {
            override fun write(bytes: ByteArray) = device.write(bytes)
            override fun read(maxBytes: Int) = device.read(maxBytes).also { clock = 2_000_000 }
        }
        assertTrue(failure { DkSwdJlinkSession(late, now = { clock }, timeoutMillis = 1).readDp(0) }.contains("timed out"))
    }

    @Test fun selectsCapturedFiveInterfaceDkDescriptorWithoutUsingCdcPorts() {
        fun ep(address: Int, type: Int = 2) = DkUsbEndpointDescriptor(address, type, 64, 1)
        fun port(index: Int, klass: Int, subclass: Int, protocol: Int, name: String, vararg endpoints: DkUsbEndpointDescriptor) =
            DkUsbInterfaceDescriptor(index,index,0,klass,subclass,protocol,name,endpoints.toList())
        val observed = listOf(port(0,2,2,1,"CDC",ep(0x82,3)),
            port(1,10,0,0,"CDC DATA interface",ep(0x81),ep(1)),
            port(2,2,2,1,"CDC",ep(0x84,3)),
            port(3,10,0,0,"CDC DATA interface",ep(0x83),ep(2)),
            port(4,255,255,255,"BULK interface",ep(0x85),ep(3)))
        val selected = DkJlinkInterfaceSelector.select(0x1366,0x1060,observed)
        assertEquals(4,selected.port?.id)
        assertEquals(0x85,selected.input?.address)
        assertEquals(3,selected.output?.address)
    }

    @Test fun rejectsArbitraryReadsAndDebugWritesBeforeSendingUsbTraffic() {
        val device = TargetModel()
        val session = DkSwdJlinkSession(device)
        for (address in listOf(0L, 0x10001000L, 0x4001e504L, 0xe000edf0L, 0x10000061L))
            assertTrue(failure { session.readFicrWord(address) }.contains("allowed"))
        for ((ap, address, value) in listOf(Triple(true, 12, 0L), Triple(true, 4, 0x10001000L),
            Triple(false, 4, 0x4000000L), Triple(false, 8, 0x1000000L), Triple(false, 0, 1L)))
            assertTrue(failure { if (ap) session.writeAp(address, value) else session.writeDp(address, value) }.contains("allowed"))
        assertTrue(device.commands.isEmpty())
    }

    /** Independent stateful J-Link/DP/AP model. Literal reply offsets are the
     * OpenOCD J-Link capture contract, not derived from the code under test. */
    internal class TargetModel : DkBulkChannel {
        val commands = mutableListOf<Int>()
        val requests = mutableListOf<Int>()
        val bitCounts = mutableListOf<Int>()
        val debugWrites = mutableListOf<Triple<Boolean, Int, Long>>()
        val memoryReads = mutableListOf<Long>()
        var corruptParity = false
        var waits = 0
        var forcedAck: Int? = null
        var probeStatus = 0
        var selectSupported = true
        var swdSupported = true
        var powerAcknowledged = true
        var dpidr = 0x2ba01477L
        var part = 0x52840L
        var apId = 0x24770011L
        var memoryEnabled = true
        var writeParityChecked = false
        var batchWaitAt: Int? = null
        var batchWaitTimes = 0
        var batchFaultAt: Int? = null
        var batchParityAt: Int? = null
        var shiftedBatch = false
        private var reply = byteArrayOf()
        private var selected = 0
        private var bank = 0
        private var tar = 0L
        private var posted = 0L
        private var csw = 0x23000042L
        private var ctrl = 0x50000000L
        private var pendingWrite: Pair<Boolean, Int>? = null
        private fun memoryValue(address: Long): Long = when(address) {
            0x10000100L -> part; 0x10000060L -> 0x12345678L; 0x10000064L -> 0xabcdef01L
            in 0..0xfffffL,in 0x10000000L..0x10001fffL -> address xor 0xa5a50000L
            else -> throw AssertionError("Forbidden memory read")
        }
        private fun debugRead(ap: Boolean,address: Int): Long = if(ap) {
            val old=posted
            posted=when(bank+address) {
                0xfc -> apId
                0 -> if(memoryEnabled) 0x23000052 else 0x23000012
                12 -> { memoryReads+=tar;memoryValue(tar).also {
                    if(csw and 0x30==0x10L)tar=(tar and 0xfffffc00L) or ((tar+4) and 0x3ff)
                } }
                else -> throw AssertionError("Unexpected AP read")
            }
            old
        } else when(address) { 0 -> dpidr;4 -> ctrl or if(powerAcknowledged)0xa0000000L else 0;12 -> posted;else -> throw AssertionError("Unexpected DP read") }
        override fun read(maxBytes: Int): ByteArray = reply.take(maxBytes).toByteArray().also { reply = reply.drop(it.size).toByteArray() }
        override fun write(bytes: ByteArray): Int {
            assertTrue("Reply must be drained before the next command", reply.isEmpty())
            val command = bytes[0].toInt() and 255
            commands += command
            fun word(value: Long) = ByteArray(4) { (value shr (it*8)).toByte() }
            when (command) {
                0xe8 -> reply = word(if (selectSupported) 1L shl 17 else 0)
                0xc7 -> {
                    reply = word(when (bytes[1].toInt() and 255) {
                        255 -> if (swdSupported) 2 else 1
                        254 -> selected.toLong()
                        1 -> selected.toLong().also { selected = 1 }
                        else -> throw AssertionError("Unexpected target interface")
                    })
                }
                0x05 -> assertArrayEquals(byteArrayOf(5, 100, 0), bytes)
                0xcf -> {
                    val count = (bytes[2].toInt() and 255) or ((bytes[3].toInt() and 255) shl 8)
                    bitCounts += count
                    val n = (count+7)/8
                    val direction = bytes.copyOfRange(4, 4+n)
                    val data = bytes.copyOfRange(4+n, bytes.size)
                    assertEquals(4+n*2, bytes.size)
                    val output = ByteArray(n)
                    fun get(offset: Int) = (data[offset/8].toInt() ushr (offset%8)) and 1
                    fun put(offset: Int, value: Long, length: Int) {
                        repeat(length) { bit -> if ((value ushr bit) and 1 == 1L) output[(offset+bit)/8] = (output[(offset+bit)/8].toInt() or (1 shl ((offset+bit)%8))).toByte() }
                    }
                    when (count) {
                        136 -> {
                            assertTrue(direction.all { it.toInt() and 255 == 255 })
                            assertArrayEquals(byteArrayOf(-1,-1,-1,-1,-1,-1,-1,0x9e.toByte(),0xe7.toByte(),-1,-1,-1,-1,-1,-1,-1,0),data)
                        }
                        64 -> {
                            assertTrue(direction.all {it.toInt() and 255==255})
                            assertArrayEquals(byteArrayOf(-1,-1,-1,-1,-1,-1,-1,0),data)
                        }
                        54, 12 -> {
                            val request = data[0].toInt() and 255
                            requests += request
                            assertEquals(1, request and 1)
                            assertEquals(0x80, request and 0xc0)
                            assertEquals(Integer.bitCount((request ushr 1) and 15) and 1, (request ushr 5) and 1)
                            assertEquals(255, direction[0].toInt() and 255)
                            val read = request and 4 != 0
                            assertEquals(read, count == 54)
                            assertArrayEquals(if (read) byteArrayOf(-1,0,0,0,0,0xc0.toByte(),0x3f) else byteArrayOf(-1,0), direction)
                            val ack = forcedAck ?: if (waits-- > 0) 2 else 1
                            put(8,ack.toLong(),3)
                            val ap = request and 2 != 0
                            val address = (request ushr 3 and 3)*4
                            if (ack == 1 && read) {
                                val value = debugRead(ap,address)
                                put(11,value,32)
                                put(43,((java.lang.Long.bitCount(value) and 1) xor if (corruptParity) 1 else 0).toLong(),1)
                            } else if (ack == 1) pendingWrite = ap to address
                        }
                        42 -> {
                            val (ap,address) = pendingWrite ?: throw AssertionError("Write data without ACK")
                            assertEquals(0, direction[0].toInt() and 1)
                            assertArrayEquals(byteArrayOf(0xfe.toByte(),-1,-1,-1,-1,3),direction)
                            var value = 0L
                            repeat(32) { value = value or (get(it+1).toLong() shl it) }
                            assertEquals(java.lang.Long.bitCount(value) and 1, get(33))
                            writeParityChecked = true
                            debugWrites += Triple(ap,address,value)
                            if (!ap && address == 8) bank = (value and 0xf0).toInt()
                            if (!ap && address == 4) ctrl = value
                            if (ap && address == 4) tar = value
                            if (ap && address == 0) csw = value
                            assertFalse("DRW writes forbidden", ap && address == 12)
                            pendingWrite = null
                        }
                        9 -> assertTrue("WAIT completion must only drive idle low", data.all { it.toInt() == 0 })
                        else -> {
                            assertTrue(count%54==0&&count in 108..6966)
                            val transactions=count/54
                            for(index in 0 until transactions) {
                                val base=index*54
                                var request=0
                                repeat(8) { request=request or (get(base+it) shl it) }
                                assertEquals(if(index==transactions-1)0xbd else 0x9f,request)
                                repeat(54) { bit -> assertEquals(bit<8||bit>=46,
                                    (direction[(base+bit)/8].toInt() ushr ((base+bit)%8)) and 1==1) }
                                val wait=count>108&&batchWaitTimes>0&&index==batchWaitAt
                                val ack=if(wait)2 else if(count>108&&index==batchFaultAt)4 else 1
                                if(wait)batchWaitTimes--
                                put(base+8,ack.toLong(),3)
                                if(ack==1) {
                                    var value=debugRead(index!=transactions-1,12)
                                    if(shiftedBatch&&count>108)value=value xor 4
                                    put(base+11,value,32)
                                    put(base+43,((java.lang.Long.bitCount(value) and 1) xor
                                        if(count>108&&index==batchParityAt)1 else 0).toLong(),1)
                                }
                            }
                        }
                    }
                    reply = output + probeStatus.toByte()
                }
                else -> throw AssertionError("Forbidden J-Link command $command")
            }
            return bytes.size
        }
    }
}
