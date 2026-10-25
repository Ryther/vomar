package org.openvimar.updater

import java.io.IOException
import org.junit.Assert.*
import org.junit.Test

class DkSwdProtocolTest {
    @Test fun enablesAndReadsBackOverrunBeforeApTrafficIncludingRetainedMode() {
        for(initial in listOf(false,true)) {
            val target=WireTarget(initial)
            DkSwdBackup.open(target)
            assertTrue(target.apModes.isNotEmpty())
            assertTrue("Fixed-frame AP access needs verified ORUNDETECT",target.apModes.all {it})
            assertTrue(target.events.contains("write:DP:4:50000001"))
            val firstSelect=target.events.indexOfFirst {it.startsWith("write:DP:8:")}
            assertTrue(target.events.take(firstSelect).contains("read:DP:4"))
            assertTrue(target.memoryWrites.isEmpty())
        }
    }

    @Test fun scalarWriteWaitAndFaultClockDummyDataWithoutDrivingTheRegisterValue() {
        val target=WireTarget();val session=session(target)
        val before=target.abortClears
        target.inject(false,false,8,2)
        assertEquals(0x12345678L,session.readFicrWord(0x10000060))
        assertEquals(1,target.dummyWrites)
        assertTrue(target.abortClears>before)
        target.inject(false,false,8,4)
        val message=failure {session.readFicrWord(0x10000060)}
        assertTrue(message.contains("FAULT"))
        assertEquals(2,target.dummyWrites)
        assertTrue(target.memoryWrites.isEmpty())
    }

    @Test fun scalarReadWaitClearsStickyOverrunBeforeRetrying() {
        val target=WireTarget();val session=session(target);val before=target.abortClears
        target.inject(true,true,12,2)
        assertEquals(0xabcdef01L,session.readFicrWord(0x10000064))
        assertTrue(target.abortClears>before)
        assertFalse(target.stickyOverrun)
        target.inject(true,true,12,4)
        assertTrue(failure {session.readFicrWord(0x10000064)}.contains("FAULT"))
    }

    @Test fun initialSelectWaitUsesTheRetainedModeBeforeEnablingOverrun() {
        for(initial in listOf(false,true)) {
            val target=WireTarget(initial)
            target.inject(false,false,8,2)
            DkSwdBackup.open(target)
            assertEquals(1,target.waitsIssued)
            assertEquals(if(initial)1 else 0,target.dummyWrites)
            assertTrue(target.apModes.all {it})
        }
    }

    @Test fun persistentScalarWaitIsBoundedAndClearsStickyBetweenAttempts() {
        val target=WireTarget();val session=session(target);val before=target.abortClears
        target.inject(true,true,12,2,times=100)
        assertTrue(failure {session.readFicrWord(0x10000060)}.contains("WAIT retry limit"))
        assertEquals(8,target.waitsIssued)
        assertEquals(7,target.abortClears-before)
        assertTrue(target.memoryWrites.isEmpty())
    }

    @Test fun batchWaitResetsThenReadsDpidrBeforeRestoringThePipeline() {
        val target=WireTarget();val source=DkSwdBackup.open(target)
        target.inject(true,true,12,2,skip=1)
        val bytes=source.readBlock(DkBackupRegion.FLASH,0,16)
        assertArrayEquals(byteArrayOf(0,0,0xa5.toByte(),0xa5.toByte(),4,0,0xa5.toByte(),0xa5.toByte(),
            8,0,0xa5.toByte(),0xa5.toByte(),12,0,0xa5.toByte(),0xa5.toByte()),bytes)
        assertEquals(2,target.events.count {it=="line-reset"})
        val reset=target.events.indexOfLast {it=="line-reset"}
        assertEquals("read:DP:0",target.events[reset+1])
        assertTrue(target.events.drop(reset).contains("write:AP:4:0"))
        assertTrue(target.apModes.all {it})
        assertTrue(target.memoryWrites.isEmpty())
    }

    @Test fun unavailableOverrunReadbackStopsBeforeAnyApAccess() {
        val target=WireTarget(ignoreOverrunWrite=true)
        assertTrue(failure {DkSwdBackup.open(target)}.contains("overrun",ignoreCase=true))
        assertTrue(target.apModes.isEmpty())
        assertTrue(target.memoryWrites.isEmpty())
    }

    @Test fun persistentWaitStopsAtTheBatchBoundWithoutReturningData() {
        val target=WireTarget();val source=DkSwdBackup.open(target)
        target.inject(true,true,12,2,times=100)
        assertTrue(failure {source.readBlock(DkBackupRegion.FLASH,0,16)}.contains("WAIT"))
        assertEquals(3,target.waitsIssued)
        assertEquals(3,target.events.count {it=="line-reset"})
        assertTrue(target.memoryWrites.isEmpty())
    }

    @Test fun changedDpidrAfterBatchResetStopsBeforeAnyOtherRegisterAccess() {
        val target=WireTarget(changedDpidrAfterReset=true);val source=DkSwdBackup.open(target)
        target.inject(true,true,12,2)
        assertTrue(failure {source.readBlock(DkBackupRegion.FLASH,0,16)}.contains("DPIDR changed"))
        val reset=target.events.indexOfLast {it=="line-reset"}
        assertEquals(listOf("read:DP:0"),target.events.drop(reset+1))
        assertTrue(target.memoryWrites.isEmpty())
    }

    private fun session(target: WireTarget)=DkSwdJlinkSession(target).also {it.initialize {_,_->};it.identify()}
    private fun failure(action: ()->Unit): String {
        try {action();fail("Expected a bounded SWD failure")}catch(error: IOException){return error.message.orEmpty()}
        return ""
    }

    /** A target state machine consumes each SWCLK/direction bit, without a
     * 54-clock transaction assumption. ADIv5 IHI0031G B4.2/B4.3 defines absent
     * WAIT/FAULT data phases with ORUN=0, dummy phases/sticky overrun with ORUN=1,
     * and mandatory DPIDR immediately after reset. J-Link capture is one clock
     * before physical ACK/data input, as independently specified by OpenOCD.
     * https://documentation-service.arm.com/static/622222b2e6f58973271ebc21 */
    private class WireTarget(initialOverrun: Boolean=false,private val ignoreOverrunWrite: Boolean=false,
        private val changedDpidrAfterReset: Boolean=false): DkBulkChannel {
        private enum class Phase { IDLE, REQUEST, TURN_TO_TARGET, ACK, READ, READ_TURN, WRITE_TURN, WRITE, ERROR, LINE_RESET }
        private data class Injection(val ap: Boolean,val read: Boolean,val address: Int,val ack: Int,var skip: Int,var remaining: Int)
        private var phase=Phase.IDLE
        private var response=byteArrayOf()
        private var selected=0
        private var initialized=false
        private var requireDpidr=true
        private var highRun=0
        private var resetLow=0
        private var request=0
        private var requestBits=0
        private var bitIndex=0
        private var ack=1
        private var ap=false
        private var read=false
        private var address=0
        private var value=0L
        private var written=0L
        private var ctrl=0x50000000L or if(initialOverrun)1L else 0L
        private var bank=0
        private var tar=0L
        private var csw=0x23000042L
        private var posted=0L
        private var injection: Injection?=null
        val events=mutableListOf<String>()
        val apModes=mutableListOf<Boolean>()
        val memoryWrites=mutableListOf<Long>()
        var stickyOverrun=false;private set
        var dummyWrites=0;private set
        var abortClears=0;private set
        var waitsIssued=0;private set
        private val overrun get()=ctrl and 1!=0L
        fun inject(ap: Boolean,read: Boolean,address: Int,ack: Int,skip: Int=0,times: Int=1) {
            injection=Injection(ap,read,address,ack,skip,times)
        }
        private fun protocol(condition: Boolean,message: String) {if(!condition)throw IOException("Target protocol violation: $message")}
        override fun read(maxBytes: Int)=response.take(maxBytes).toByteArray().also {response=response.drop(it.size).toByteArray()}
        override fun write(bytes: ByteArray): Int {
            protocol(response.isEmpty(),"undrained USB response")
            fun word(number: Long)=ByteArray(4){(number ushr (it*8)).toByte()}
            when(bytes[0].toInt() and 255) {
                0xe8->response=word(1L shl 17)
                0xc7->response=word(when(bytes[1].toInt() and 255) {255->2;254->selected.toLong();1->selected.toLong().also {selected=1};else->error("Unsupported interface")})
                5->protocol(bytes.contentEquals(byteArrayOf(5,100,0)),"unexpected speed")
                0xcf->{
                    val count=(bytes[2].toInt() and 255) or ((bytes[3].toInt() and 255) shl 8)
                    val n=(count+7)/8;protocol(bytes.size==4+2*n,"malformed raw packet")
                    val captured=ByteArray(n)
                    if(!initialized&&count==136) {
                        initialized=true;requireDpidr=true;events+="line-reset"
                        if(overrun)stickyOverrun=true
                    } else repeat(count) {index->
                        val drive=(bytes[4+index/8].toInt() ushr (index%8)) and 1==1
                        val output=(bytes[4+n+index/8].toInt() ushr (index%8)) and 1
                        clock(drive,output) {sample->
                            val position=index-1
                            protocol(position>=0,"input sample straddled packet boundary")
                            if(sample!=0)captured[position/8]=(captured[position/8].toInt() or (1 shl (position%8))).toByte()
                        }
                    }
                    response=captured+byteArrayOf(0)
                }
                else->throw IOException("Forbidden USB command")
            }
            return bytes.size
        }
        private fun clock(drive: Boolean,output: Int,capture: (Int)->Unit) {
            highRun=if(drive&&output==1)highRun+1 else 0
            if(highRun>=50) {phase=Phase.LINE_RESET;resetLow=0;return}
            if(phase==Phase.LINE_RESET) {
                protocol(drive,"line reset released unexpectedly")
                if(output==0)resetLow++ else resetLow=0
                if(resetLow==2) {
                    events+="line-reset";phase=Phase.IDLE;requireDpidr=true
                    if(overrun)stickyOverrun=true
                }
                return
            }
            when(phase) {
                Phase.ERROR->Unit
                Phase.IDLE->{
                    protocol(drive,"host released idle after a transfer without a data phase")
                    if(output==1) {request=1;requestBits=1;phase=Phase.REQUEST}
                }
                Phase.REQUEST->{
                    protocol(drive,"request was not driven")
                    request=request or (output shl requestBits++)
                    if(requestBits==8) {
                        if(request and 0xc0!=0x80 || Integer.bitCount((request ushr 1) and 15) and 1!=(request ushr 5) and 1) {phase=Phase.ERROR;return}
                        ap=request and 2!=0;read=request and 4!=0;address=(request ushr 3 and 3)*4
                        protocol(!requireDpidr||!ap&&read&&address==0,"DPIDR required immediately after line reset")
                        events+="${if(read)"read" else "request-write"}:${if(ap)"AP" else "DP"}:$address"
                        if(ap)apModes+=overrun
                        ack=chooseAck()
                        value=if(ack==1&&read)debugRead() else 0L
                        if(!ap&&read&&address==0&&ack==1)requireDpidr=false
                        phase=Phase.TURN_TO_TARGET
                    }
                }
                Phase.TURN_TO_TARGET->{protocol(!drive,"request turnaround driven");phase=Phase.ACK;bitIndex=0}
                Phase.ACK->{
                    protocol(!drive,"ACK driven by host");capture((ack ushr bitIndex) and 1)
                    if(++bitIndex==3) {
                        bitIndex=0
                        phase=if(read&&(ack==1||overrun))Phase.READ else if(read)Phase.READ_TURN else Phase.WRITE_TURN
                    }
                }
                Phase.READ->{
                    protocol(!drive,"read data driven by host")
                    // WAIT/FAULT read data is undriven/unknown. Pull-up samples
                    // intentionally have invalid parity and must be discarded.
                    capture(if(ack!=1)1 else if(bitIndex==32)java.lang.Long.bitCount(value) and 1 else (value ushr bitIndex).toInt() and 1)
                    if(++bitIndex==33)phase=Phase.READ_TURN
                }
                Phase.READ_TURN->{protocol(!drive,"read turnaround driven");phase=Phase.IDLE}
                Phase.WRITE_TURN->{
                    protocol(!drive,"write turnaround driven")
                    if(ack==1||overrun) {phase=Phase.WRITE;written=0;bitIndex=0} else phase=Phase.IDLE
                }
                Phase.WRITE->{
                    protocol(drive,"write data not driven")
                    if(ack!=1)protocol(output==0,"WAIT/FAULT dummy data contains a register value")
                    if(bitIndex<32)written=written or (output.toLong() shl bitIndex)
                    else {
                        protocol(output==java.lang.Long.bitCount(written) and 1,"bad write parity")
                        if(ack==1)debugWrite(written) else dummyWrites++
                        phase=Phase.IDLE
                    }
                    bitIndex++
                }
                Phase.LINE_RESET->error("Handled above")
            }
        }
        private fun chooseAck(): Int {
            if(!ap&&(read&&address in listOf(0,4)||!read&&address==0))return 1
            if(stickyOverrun)return 4
            val inject=injection
            if(inject!=null&&inject.remaining>0&&inject.ap==ap&&inject.read==read&&inject.address==address) {
                if(inject.skip>0)inject.skip--
                else {
                    inject.remaining--
                    if(inject.ack==2)waitsIssued++
                    if(overrun&&inject.ack!=1)stickyOverrun=true
                    return inject.ack
                }
            }
            return 1
        }
        private fun debugRead(): Long {
            if(!ap)return when(address) {0->if(changedDpidrAfterReset&&events.count {it=="line-reset"}>1)0x12345677 else 0x2ba01477;4->ctrl or 0xa0000000L or if(stickyOverrun)2L else 0;12->posted;else->error("Unexpected DP read")}
            val old=posted
            posted=when(bank+address) {
                0xfc->0x24770011;0->csw
                12->{
                    val word=when(tar) {0x10000100L->0x52840L;0x10000060L->0x12345678L;0x10000064L->0xabcdef01L;else->tar xor 0xa5a50000L}
                    protocol(tar in 0..0xfffffL||tar in 0x10000000L..0x10001fffL,"forbidden memory read")
                    if(csw and 0x30==0x10L)tar=(tar and 0xfffffc00L) or ((tar+4) and 0x3ff)
                    word
                }
                else->error("Unexpected AP read")
            }
            return old
        }
        private fun debugWrite(data: Long) {
            events+="write:${if(ap)"AP" else "DP"}:$address:${data.toString(16)}"
            if(ap)when(address) {
                0->csw=data;4->tar=data
                else->{memoryWrites+=data;throw IOException("Forbidden memory write")}
            } else when(address) {
                0->{protocol(data==0x1eL,"ABORT policy broadened");stickyOverrun=false;abortClears++}
                4->{protocol(data in listOf(0x50000000L,0x50000001L),"CTRL/STAT policy broadened");ctrl=if(ignoreOverrunWrite)data and 1L.inv() else data}
                8->{protocol(data in listOf(0L,0xf0L),"APSEL policy broadened");bank=(data and 0xf0).toInt()}
                else->throw IOException("Forbidden DP write")
            }
        }
    }
}
