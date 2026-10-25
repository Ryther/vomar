package org.openvimar.updater

import java.io.IOException
import java.util.Locale

/** Packet-sized USB reads with a retained tail. A short logical read must not
 * truncate a coalesced reply packet. libjaylink transport_usb.c uses 2048-byte
 * receive buffers for the same transport constraint. No commands are added. */
internal class DkSwdBufferedChannel(private val raw: DkBulkChannel) : DkBulkChannel {
    private var pending = byteArrayOf()
    private var offset = 0
    override fun write(bytes: ByteArray) = raw.write(bytes)
    override fun read(maxBytes: Int): ByteArray {
        if (maxBytes !in 1..2048) throw IOException("Invalid USB reply bound")
        if (offset == pending.size) {
            pending = raw.read(2048)
            offset = 0
            if (pending.isEmpty() || pending.size > 2048) throw IOException("J-Link USB reply was empty or oversized")
        }
        val end = minOf(pending.size, offset + maxBytes)
        return pending.copyOfRange(offset, end).also { offset = end }
    }
}

/** Original narrow protocol implementation, without linked/copied GPL code.
 * Protocol references (read as wire specifications):
 * libjaylink 5b9ab7b06249af69d349c3ce8b29e8769845071e: device.c, target.c,
 * swd.c and transport_usb.c, https://gitlab.zapb.de/libjaylink/libjaylink
 * OpenOCD c3cda13d215b1679817a492f54ef194212e01752: jlink_swd_queue_cmd /
 * jlink_swd_run_queue (J-Link captures ACK at bit8, data at bit11),
 * https://github.com/openocd-org/openocd/blob/c3cda13d215b1679817a492f54ef194212e01752/src/jtag/drivers/jlink.c
 * ARM CMSIS-DAP SW_DP.c: request/data parity, OK/WAIT/FAULT and turnaround,
 * https://github.com/ARM-software/CMSIS-DAP/blob/main/Firmware/Source/SW_DP.c
 * This code cannot write DRW, CTRL-AP, system memory, reset or halt registers.
 */
internal class DkSwdJlinkSession(private val channel: DkBulkChannel,
    private val now: () -> Long = System::nanoTime, timeoutMillis: Long = 15000,
    private val cancelled: () -> Boolean = {false}) {
    private val started = now()
    private val timeoutNanos = timeoutMillis * 1_000_000
    private var originalCsw: Long? = null
    private var identified: DkBackupIdentity? = null
    private var overrunDataPhase: Boolean? = null
    private var fixedDataPhaseVerified = false

    private fun checkTime() {
        if(cancelled()) throw IOException("Backup cancelled; no partial archive is available")
        if (now() - started >= timeoutNanos) throw IOException("SWD diagnostics timed out")
    }

    private fun send(bytes: ByteArray) {
        checkTime()
        if (channel.write(bytes) != bytes.size) throw IOException("J-Link USB command was incomplete")
        checkTime()
    }

    private fun receive(size: Int): ByteArray {
        if (size !in 1..2048) throw IOException("Invalid SWD reply bound")
        val result = ByteArray(size)
        var offset = 0
        while (offset < size) {
            checkTime()
            val bytes = channel.read(size-offset)
            checkTime()
            if (bytes.isEmpty() || bytes.size > size-offset) throw IOException("J-Link USB reply was incomplete")
            bytes.copyInto(result, offset)
            offset += bytes.size
        }
        return result
    }

    private fun word(bytes: ByteArray): Long = bytes.foldIndexed(0L) { index, value, byte ->
        value or ((byte.toLong() and 255) shl (index*8))
    }

    private fun query(vararg bytes: Int): Long {
        send(ByteArray(bytes.size) { bytes[it].toByte() })
        return word(receive(4))
    }

    fun initialize(observe: (String, Any) -> Unit) {
        val capabilities = query(0xe8)
        observe("probeCapabilities", hex(capabilities))
        if (capabilities and (1L shl 17) == 0L) throw IOException("J-Link does not report target interface selection")
        val available = query(0xc7, 0xff)
        observe("availableInterfaces", hex(available))
        if (available and 2L == 0L) throw IOException("J-Link does not report SWD support")
        observe("previousInterface", query(0xc7, 1))
        if (query(0xc7, 0xfe) != 1L) throw IOException("J-Link did not select SWD")
        send(byteArrayOf(5, 100, 0)) // 100 kHz; this is debug clock, not target power.
        observe("swdClockKhz", 100)
        val direction = BooleanArray(136) { true }
        val output = BooleanArray(136)
        repeat(56) { output[it] = true; output[it+72] = true }
        repeat(16) { output[it+56] = (0xe79e ushr it) and 1 == 1 }
        observe("swdLineSynchronizationAttempted", true)
        clocks(direction, output) // SWJ line synchronization only; never nRESET.
    }

    private fun clocks(direction: BooleanArray, output: BooleanArray): ByteArray {
        val count = direction.size
        if (count !in 1..6966 || output.size != count) throw IOException("Invalid SWD clock bound")
        val n = (count+7)/8
        val command = ByteArray(4+n*2)
        command[0] = 0xcf.toByte()
        command[2] = count.toByte()
        command[3] = (count ushr 8).toByte()
        repeat(count) { index ->
            val mask = 1 shl (index%8)
            if (direction[index]) command[4+index/8] = (command[4+index/8].toInt() or mask).toByte()
            if (output[index]) command[4+n+index/8] = (command[4+n+index/8].toInt() or mask).toByte()
        }
        send(command)
        val response = receive(n+1)
        val status = response[n].toInt() and 255
        if (status != 0) throw IOException("J-Link SWD I/O status $status")
        return response.copyOf(n)
    }

    private fun bits(bytes: ByteArray, offset: Int, count: Int): Long {
        var value = 0L
        repeat(count) { index ->
            if ((bytes[(offset+index)/8].toInt() ushr ((offset+index)%8)) and 1 == 1)
                value = value or (1L shl index)
        }
        return value
    }

    private fun transfer(ap: Boolean, read: Boolean, address: Int, value: Long = 0): Long {
        // DPIDR/CTRL reads and ABORT writes always ACK OK (ADIv5 B4.2.3/.4).
        // Learn the retained mode before a SELECT/CTRL write could return WAIT.
        if(overrunDataPhase==null && !ap && !(read&&address in listOf(0,4)) && !(!read&&address==0)) readDp(4)
        if((ap || read&&address==12) && !fixedDataPhaseVerified)
            throw IOException("SWD fixed data phase requires verified overrun detection")
        var request = 0x81 or (if (ap) 2 else 0) or (if (read) 4 else 0) or ((address and 12) shl 1)
        request = request or ((Integer.bitCount((request ushr 1) and 15) and 1) shl 5)
        repeat(8) {attempt->
            val direction = BooleanArray(if (read) 54 else 12) { bit -> bit < 8 || read && bit >= 46 }
            val output = BooleanArray(direction.size) { bit -> bit < 8 && (request ushr bit) and 1 == 1 }
            val reply = clocks(direction, output)
            val ack = bits(reply, 8, 3).toInt()
            if (!read && ack in listOf(1, 2, 4)) {
                // ORUNDETECT requires a dummy data phase even for WAIT/FAULT.
                // Only an OK response permits driving the actual register value.
                val finishDirection = BooleanArray(if (ack == 1 || overrunDataPhase==true) 42 else 9) { bit -> bit != 0 }
                val finishOutput = BooleanArray(finishDirection.size)
                if (ack == 1) {
                    repeat(32) { bit -> finishOutput[bit+1] = (value ushr bit) and 1 == 1L }
                    finishOutput[33] = java.lang.Long.bitCount(value) and 1 == 1
                }
                clocks(finishDirection, finishOutput)
            }
            when (ack) {
                1 -> {
                    if (!read) return 0
                    val data = bits(reply, 11, 32)
                    if (bits(reply, 43, 1).toInt() != java.lang.Long.bitCount(data) and 1)
                        throw IOException("SWD read parity mismatch")
                    return data
                }
                2 -> {
                    if(attempt==7)throw IOException("SWD WAIT retry limit reached")
                    if(overrunDataPhase==true) {
                        if(!ap&&!read&&address==0)throw IOException("Unexpected SWD WAIT on ABORT")
                        // A WAIT sets STICKYORUN in this mode; the next AP/SELECT
                        // request otherwise returns FAULT. ABORT is always OK.
                        transfer(false,false,0,0x1e)
                    }
                }
                4 -> throw IOException("SWD FAULT; target access may be protected. No recovery or erase was attempted.")
                else -> throw IOException("Invalid SWD ACK $ack; check the selected target and SWD wiring")
            }
        }
        throw IOException("SWD WAIT retry limit reached")
    }

    fun readDp(address: Int): Long {
        if (address !in listOf(0, 4, 12)) throw IOException("DP read is not allowed")
        return transfer(false, true, address).also {if(address==4) {
            overrunDataPhase=it and 1!=0L
            if(overrunDataPhase!=true)fixedDataPhaseVerified=false
        }}
    }

    fun writeDp(address: Int, value: Long) {
        val allowed = address == 0 && value == 0x1eL || address == 4 && value == 0x50000001L ||
            address == 8 && value in listOf(0L, 0xf0L)
        if (!allowed) throw IOException("DP write is not allowed")
        transfer(false, false, address, value)
        if(address==4) {
            overrunDataPhase=value and 1!=0L
            fixedDataPhaseVerified=false // A write alone never proves target support.
        }
    }

    private fun readAp(address: Int): Long {
        writeDp(8, (address and 0xf0).toLong()) // APSEL0 only.
        transfer(true, true, address and 12) // AP reads are posted.
        return readDp(12)
    }

    fun writeAp(address: Int, value: Long) {
        val allowed = address == 0 && value in 0..0xffffffffL && value and 0x37 == 2L ||
            address == 4 && value in FICR_WORDS
        if (!allowed) throw IOException("AP write is not allowed")
        writeDp(8, 0)
        transfer(true, false, address, value)
        readDp(12) // Complete the posted write before using the AP again.
    }

    /** ADIv5 IHI0031G B4.2: fixed READ frames require ORUNDETECT on every
     * WAIT/FAULT response. Do not issue AP traffic until the target confirms it.
     * https://documentation-service.arm.com/static/622222b2e6f58973271ebc21 */
    private fun configureFixedDataPhase(observe: (String,Any)->Unit = {_,_->}) {
        fixedDataPhaseVerified=false
        val before=readDp(4)
        observe("overrunDataPhaseInitiallyEnabled",before and 1!=0L)
        writeDp(0, 0x1e) // Clear sticky status only; DAPABORT bit0 stays clear.
        writeDp(8, 0)
        writeDp(4, 0x50000001) // Debug/system power plus ORUNDETECT; never reset bits.
        observe("debugDomainPowerRequested", true)
        var powered = false
        repeat(20) { if (!powered) {
            val status=readDp(4)
            if(status and 1==0L)throw IOException("Target did not enable SWD overrun detection")
            powered=status and 0xa0000000L==0xa0000000L
        }}
        if (!powered) throw IOException("Debug power acknowledgement timed out")
        fixedDataPhaseVerified=true
        observe("overrunDataPhaseVerified",true)
    }

    fun prepareMemoryReads(observe: (String, Any) -> Unit) {
        configureFixedDataPhase(observe)
        val apId = readAp(0xfc)
        observe("ap0Idr", hex(apId))
        if (apId and 15 != 1L || (apId ushr 13) and 15 != 8L) throw IOException("AP0 is not a supported AHB memory access port")
        val csw = readAp(0)
        originalCsw=csw
        observe("ap0CswBefore", hex(csw))
        if (csw and 0x40 == 0L) throw IOException("Target memory access is disabled; no unlock or erase was attempted")
        writeAp(0, (csw and 0xffffffc8L) or 2L) // 32-bit, no address increment; preserve other fields.
    }

    fun readFicrWord(address: Long): Long {
        if (address !in FICR_WORDS) throw IOException("Target memory address is not allowed")
        writeAp(4, address)
        return readAp(12)
    }

    fun identify(observe: (String,Any)->Unit = {_,_->}): DkBackupIdentity {
        val dpidr=readDp(0)
        observe("dpidr",hex(dpidr))
        if(dpidr!=0x2ba01477L) throw IOException("Unsupported DPIDR; this diagnostic supports the nRF52840 debug port only")
        prepareMemoryReads(observe)
        observe("ficrReadAttempted",true)
        val part=readFicrWord(0x10000100)
        observe("part",hex(part))
        if(part!=0x52840L) throw IOException("The connected target did not report nRF52840 PART")
        val uid0=readFicrWord(0x10000060);val uid1=readFicrWord(0x10000064)
        observe("uid",listOf(hex(uid0),hex(uid1)))
        if(readDp(4) and 0xa2!=0L) throw IOException("SWD debug status reports an access error")
        observe("targetChip","nRF52840");observe("commercialModelVerified",false);observe("identityReadVerified",true)
        return DkBackupIdentity(uid0,uid1,part).also { identified=it }
    }

    private class BatchWait: IOException()

    /** Separate read-only capability. Public diagnostic writeAp/readFicrWord
     * keep their original narrow policy. There is no arbitrary memory API.
     * ADIv5 guarantees TAR auto-increment only within a 1KiB window:
     * https://documentation-service.arm.com/static/622222b2e6f58973271ebc21
     * Posted AP reads are drained by a final DP RDBUFF; no DRW write exists. */
    fun openBackupSource(): DkBackupSource {
        val identity=identified ?: throw IOException("Live identity must be verified before backup")
        val csw=((originalCsw ?: throw IOException("AP0 is not initialized")) and 0xffffffc8L) or 0x12L
        var cswConfigured=false
        fun span(address: Long,length: Int) {
            if(length !in 4..512 || length%4!=0 || address%4!=0L || address%1024+length>1024 ||
                DkBackupRegion.entries.none { address>=it.start&&address+length<=it.start+it.size })
                throw IOException("Backup read span is not allowed")
        }
        fun setup(address: Long) {
            writeDp(8,0)
            if(!cswConfigured) { transfer(true,false,0,csw);readDp(12);cswConfigured=true }
            transfer(true,false,4,address);readDp(12)
        }
        fun burst(address: Long,words: Int): ByteArray {
            span(address,words*4)
            repeat(3) { attempt ->
                checkTime();setup(address)
                val count=(words+1)*54
                val direction=BooleanArray(count) { it%54<8||it%54>=46 }
                val output=BooleanArray(count) { index ->
                    val request=if(index/54==words)0xbd else 0x9f
                    index%54<8&&(request ushr (index%54)) and 1==1
                }
                val reply=clocks(direction,output)
                try {
                    val values=LongArray(words+1)
                    for(index in values.indices) {
                        val base=index*54
                        when(val ack=bits(reply,base+8,3).toInt()) {
                            1 -> Unit
                            2 -> throw BatchWait()
                            4 -> throw IOException("SWD FAULT in backup batch; no unlock or erase was attempted")
                            else -> throw IOException("Invalid SWD ACK $ack in backup batch")
                        }
                        val value=bits(reply,base+11,32)
                        if(bits(reply,base+43,1).toInt()!=java.lang.Long.bitCount(value) and 1)
                            throw IOException("SWD backup read parity mismatch")
                        values[index]=value
                    }
                    return ByteArray(words*4) { index -> (values[index/4+1] ushr ((index%4)*8)).toByte() }
                } catch(wait: BatchWait) {
                    if(attempt==2)throw IOException("SWD WAIT backup batch retry limit reached")
                    // A failed posted-read pipeline is never reused. Return the
                    // SWD protocol to line-idle before any further DP/AP writes.
                    clocks(BooleanArray(64) {true},BooleanArray(64) {it<56})
                    // ADIv5 B4.3.3: DPIDR must leave reset state before ABORT,
                    // SELECT or any other request. Line reset retains DP mode.
                    fixedDataPhaseVerified=false
                    if(readDp(0)!=0x2ba01477L)throw IOException("SWD DPIDR changed after batch retry synchronization")
                    configureFixedDataPhase()
                    cswConfigured=false
                }
            }
            throw IOException("Backup batch did not complete")
        }
        return object: DkBackupSource {
            override val identity=identity
            override fun currentIdentity(): DkBackupIdentity {
                checkTime()
                val part=readFicrWord(0x10000100)
                return DkBackupIdentity(readFicrWord(0x10000060),readFicrWord(0x10000064),part)
            }
            override fun readBlock(region: DkBackupRegion,offset: Int,length: Int): ByteArray {
                checkTime()
                if(offset<0||offset.toLong()+length>region.size)throw IOException("Backup region bounds are not allowed")
                val address=region.start+offset
                span(address,length)
                val bytes=burst(address,length/4)
                val first=burst(address,1)
                val last=if(length==4)first else burst(address+length-4,1)
                if(!first.contentEquals(bytes.copyOfRange(0,4)) || !last.contentEquals(bytes.copyOfRange(bytes.size-4,bytes.size)))
                    throw IOException("Independent backup block sentinel mismatch")
                if(readDp(4) and 0xa2!=0L)throw IOException("Backup debug status reports an access error")
                checkTime()
                return bytes
            }
        }
    }

    companion object {
        private val FICR_WORDS = setOf(0x10000100L, 0x10000060L, 0x10000064L)
        fun hex(value: Long): String = String.format(Locale.ROOT, "0x%08x", value)
    }
}

internal object DkSwdReadOnly {
    /** nRF52840 FICR offsets: Nordic product specification, FICR chapter:
     * https://docs.nordicsemi.com/r/bundle/ps_nrf52840/page/ficr.html
     * FICR identifies silicon. It does not identify a Vimar commercial product. */
    fun probe(channel: DkBulkChannel, observe: (String, Any) -> Unit = { _, _ -> }) {
        val session = DkSwdJlinkSession(channel)
        session.initialize(observe)
        session.identify(observe)
    }
}
