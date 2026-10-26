package org.openvimar.updater.installer

import java.io.IOException

/** Independent per-clock ADIv5/J-Link target from the reviewed protocol fixture;
 * NVMC/CPU state applies target register semantics, never calls production code. */
internal class ProgrammingWireTarget(initialOverrun: Boolean=false,private val ignoreOverrunWrite: Boolean=false,
        private val changedDpidrAfterReset: Boolean=false): InstallBulkChannel {
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
        val requestedPowerBits get()=ctrl and 0x50000000L
        private var debugPowerReleased=false
        private var bank=0
        private var tar=0L
        private var csw=0x23000042L
        private var posted=0L
        private var injection: Injection?=null
        val events=mutableListOf<String>()
        var logLimit=Int.MAX_VALUE
        val apModes=mutableListOf<Boolean>()
        val memoryWrites=mutableListOf<Pair<Long,Long>>()
        val flash=ByteArray(0x100000){0xff.toByte()}
        var halted=false
        var debugControl=0L
        var mode=0
        val flashAcl=Array(8){longArrayOf(0,0,0)}
        var retainAclOnReset=false
        var faultOnProtectedErase=false
        private fun writable(address:Long,size:Int)=flashAcl.none{r->
            r[0]%4096==0L&&r[1]>0&&r[1]%4096==0L&&r[2] and 2L!=0L&&address<r[0]+r[1]&&address+size>r[0]
        }
        var corruptUicr=false
        var wdtRunning=false
        var wdtConfig=1L
        var wdtCrv=0xffffffffL
        var wdtRren=0L
        var wdtRunsWhileHalted:Boolean
            get()=wdtConfig and 8L!=0L
            set(value){wdtConfig=if(value)wdtConfig or 8L else wdtConfig and 8L.inv()}
        var neverReady=false
        var corruptReadParity=false
        var corruptReadParityCount=0
        var demcr=0L
        var resetCount=0
        var resetSeen=false
        var ignoreVectorCatch=false
        var stockInstructions=0
        var onMemoryWrite:(Long,Long)->Unit={_,_->}
        var wrongResetPc=false
        var wrongResetMsp=false
        var registerNeverReady=false
        var registerDelay=0
        var corePc=0x1000L
        var coreMsp=0x20020000L
        var coreXpsr=0x01000000L
        var uid0=0x12345678L
        var uid1=0xabcdef01L
        private var registerData=0L
        fun firmwareReset(watchdog:Boolean=false){
            // Nordic POWER reset behavior: SYSRESETREQ does NOT reset WDT.
            // Only the independently modeled actual watchdog-reset event does.
            resetCount++;resetSeen=true;mode=0
            if(!retainAclOnReset)flashAcl.forEach{it.fill(0)}
            if(watchdog){wdtRunning=false;debugControl=0;demcr=0;csw=0x23000042L;bank=0}
            halted=debugControl and 1!=0L&&demcr and 1!=0L&&!ignoreVectorCatch
            debugControl=debugControl and 1L or if(halted)2L else 0L
            corePc=(memory(4) and 0xfffffffeL) xor if(wrongResetPc)4L else 0L;coreMsp=(memory(0) and 0xfffffffcL) xor if(wrongResetMsp)8L else 0L
            coreXpsr=(memory(4) and 1L) shl 24
            if(!halted)stockInstructions++
        }
        private var stickyAccessFault=false
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
                        initialized=true;requireDpidr=true;if(events.size<logLimit)events+="line-reset"
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
                    if(events.size<logLimit)events+="line-reset";phase=Phase.IDLE;requireDpidr=true
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
                        if(events.size<logLimit)events+="${if(read)"read" else "request-write"}:${if(ap)"AP" else "DP"}:$address"
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
                    capture(if(ack!=1)1 else if(bitIndex==32)readParity(value) else (value ushr bitIndex).toInt() and 1)
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
            if(stickyOverrun||stickyAccessFault)return 4
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
        private fun readParity(value:Long):Int {
            val bad=corruptReadParity||corruptReadParityCount>0
            if(corruptReadParityCount>0)corruptReadParityCount--
            return (java.lang.Long.bitCount(value) and 1) xor if(bad)1 else 0
        }
        private fun debugRead(): Long {
            if(ap)protocol(!debugPowerReleased,"AP access after normal debug-session powerdown")
            if(!ap)return when(address) {0->if(changedDpidrAfterReset&&events.count {it=="line-reset"}>1)0x12345677 else 0x2ba01477;4->ctrl or 0xa0000000L or if(stickyOverrun)2L else 0L or if(stickyAccessFault)0x20L else 0L;12->posted;else->error("Unexpected DP read")}
            val old=posted
            posted=when(bank+address) {
                0xfc->0x24770011;0->csw
                12->{
                    val word=memory(tar)
                    if(csw and 0x30==0x10L)tar=(tar and 0xfffffc00L) or ((tar+4) and 0x3ff)
                    word
                }
                else->error("Unexpected AP read")
            }
            return old
        }
        private fun memory(at:Long):Long=when(at){
            0x10000010L->4096;0x10000014L->256;0x10000100L->0x52840;0x10000104L->0x41414430
            0x1000010cL->256;0x10000110L->1024;0x10000060L->uid0;0x10000064L->uid1
            0xe000edf0L->(debugControl or (if(halted)0x20000L else 0L) or (if(resetSeen)0x02000000L else 0L) or
                (if(!registerNeverReady&&registerDelay--<=0)0x10000L else 0L)).also{resetSeen=false}
            0xe000edf8L->{protocol(!registerNeverReady&&registerDelay<0,"DCRDR read before S_REGRDY handshake");registerData}
            0xe000edfcL->demcr
            0xe000ed0cL->0xfa050000L
            0x4001e400L->if(neverReady)0 else 1
            0x4001e504L->mode.toLong()
            in 0x4001e800L..0x4001e87bL->{
                val offset=(at-0x4001e800L).toInt();val field=offset%16/4
                protocol(field<3,"reserved ACL register read");flashAcl[offset/16][field]
            }
            0x40010400L->if(wdtRunning)1 else 0
            0x40010504L->wdtCrv
            0x40010508L->wdtRren
            0x4001050cL->wdtConfig
            in 0L..0xffffcL->(0..3).fold(0L){v,i->v or ((flash[at.toInt()+i].toLong() and 255) shl (8*i))}
            0x10001000L->if(corruptUicr)0 else 0xffffffffL
            in 0x10000000L..0x10001ffcL->0xffffffffL
            else->throw IOException("Forbidden memory read $at")
        }
        private fun debugWrite(data: Long) {
            if(ap)protocol(!debugPowerReleased,"AP write after normal debug-session powerdown")
            if(events.size<logLimit)events+="write:${if(ap)"AP" else "DP"}:$address:${data.toString(16)}"
            if(ap)when(address) {
                0->csw=data;4->tar=data
                12->{
                    memoryWrites+=tar to data
                    when(tar){
                        0xe000edf0L->{protocol(data ushr 16==0xa05fL,"DHCSR key");debugControl=data and 0xffff;halted=debugControl and 2!=0L;if(!halted)stockInstructions++}
                        0xe000edfcL->{demcr=data}
                        0xe000ed0cL->{protocol(data==0x05fa0004L,"SYSRESETREQ key/bit policy");firmwareReset()}
                        0xe000edf4L->{protocol(halted&&data in setOf(0x0fL,0x10L,0x11L),"DCRSR must request READ of PC/xPSR/MSP only; no REGWnR")
                            registerData=when(data){0x0fL->corePc;0x10L->coreXpsr;0x11L->coreMsp;else->error("Forbidden selector")};registerDelay=1}
                        0x4001e504L->{protocol(halted&&data in 0..2,"NVMC mode");mode=data.toInt()}
                        0x4001e508L->{protocol(halted&&mode==2&&data%4096==0L&&data in 0..0xff000,"page erase");if(!writable(data,4096)){if(faultOnProtectedErase)stickyAccessFault=true} else flash.fill(0xff.toByte(),data.toInt(),data.toInt()+4096)}
                        in 0L..0xffffcL->{protocol(halted&&mode==1,"FLASH program without halt/write mode");if(writable(tar,4))repeat(4){i->val v=(data ushr (i*8)).toByte();protocol(flash[tar.toInt()+i].toInt() and v.toInt()==v.toInt(),"NOR0->1");flash[tar.toInt()+i]=v}}
                        else->throw IOException("Forbidden memory write $tar")
                    }
                    onMemoryWrite(memoryWrites.last().first,data)
                    if(csw and 0x30==0x10L)tar=(tar and 0xfffffc00L) or ((tar+4) and 0x3ff)
                }
                else->error("Forbidden AP write")
            } else when(address) {
                0->{protocol(data==0x1eL,"ABORT policy broadened");stickyOverrun=false;stickyAccessFault=false;abortClears++}
                4->{protocol(data in listOf(1L,0x50000000L,0x50000001L),"CTRL/STAT policy broadened")
                    if(data==1L)protocol(debugControl and 1==0L&&demcr and 1==0L,"Powerdown must follow DEBUGEN0/VC0 normal release")
                    debugPowerReleased=data==1L;ctrl=if(ignoreOverrunWrite)data and 1L.inv() else data}
                8->{protocol(data in listOf(0L,0xf0L),"APSEL policy broadened");bank=(data and 0xf0).toInt()}
                else->throw IOException("Forbidden DP write")
            }
        }
    }
