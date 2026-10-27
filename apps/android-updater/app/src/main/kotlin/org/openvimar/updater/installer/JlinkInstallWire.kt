package org.openvimar.updater.installer

import java.io.IOException

internal interface InstallBulkChannel {
    fun write(bytes:ByteArray):Int
    fun read(maxBytes:Int):ByteArray
}

/** Separate programming capability; the existing diagnostic wire is unchanged.
 * Wire specifications: libjaylink 5b9ab7b06249af69d349c3ce8b29e8769845071e,
 * https://gitlab.zapb.de/libjaylink/libjaylink ; OpenOCD J-Link capture offsets
 * https://github.com/openocd-org/openocd/blob/c3cda13d215b1679817a492f54ef194212e01752/src/jtag/drivers/jlink.c
 * ADIv5 IHI0031G B4 (ORUN/turnaround/posted AP accesses):
 * https://documentation-service.arm.com/static/622222b2e6f58973271ebc21
 * NVMC addresses/word/page requirements:
 * https://docs.nordicsemi.com/r/bundle/ps_nrf52840/page/nvmc.html
 * No CTRL-AP, UICR, mass-erase or arbitrary peripheral write exists. The sole
 * reset command requires previously enabled/read-back reset vector catch. */
internal class JlinkInstallWire(private val channel:InstallBulkChannel,
    private val checkTransport:()->Unit={},private val now:()->Long=System::nanoTime) {
    private var pending=byteArrayOf();private var pendingOffset=0
    private var overrun:Boolean?=null;private var ready=false;private var csw=0L
    private var originalDemcr:Long?=null
    private var selectedBank:Long?=null;private var configuredCsw:Long?=null
    private fun invalidateCaches(){selectedBank=null;configuredCsw=null}
    private fun send(data:ByteArray){try{checkTransport();if(channel.write(data)!=data.size)throw IOException("Incomplete programming USB command");checkTransport()}
        catch(error:Exception){invalidateCaches();throw error}}
    private fun receive(length:Int):ByteArray {
        require(length in 1..2048);val out=ByteArray(length);var at=0
        while(at<length){checkTransport();if(pendingOffset==pending.size){pending=channel.read(2048);pendingOffset=0;require(pending.size in 1..2048){"Incomplete programming USB reply"}}
            val n=minOf(length-at,pending.size-pendingOffset);pending.copyInto(out,at,pendingOffset,pendingOffset+n);at+=n;pendingOffset+=n;checkTransport()}
        return out
    }
    private fun query(vararg command:Int):Long {send(ByteArray(command.size){command[it].toByte()});return bits(receive(4),0,32)}
    private fun clocks(direction:BooleanArray,data:BooleanArray):ByteArray {
        val count=direction.size;require(count in 1..6966&&data.size==count);val n=(count+7)/8;val command=ByteArray(4+2*n)
        command[0]=0xcf.toByte();command[2]=count.toByte();command[3]=(count ushr 8).toByte()
        repeat(count){i->val bit=1 shl(i%8);if(direction[i])command[4+i/8]=(command[4+i/8].toInt() or bit).toByte();if(data[i])command[4+n+i/8]=(command[4+n+i/8].toInt() or bit).toByte()}
        send(command);val reply=try{receive(n+1)}catch(error:Exception){invalidateCaches();throw error}
        if(reply[n]!=0.toByte()){invalidateCaches();throw IOException("Programming SWD probe status ${reply[n].toInt() and 255}")};return reply.copyOf(n)
    }
    private fun bits(data:ByteArray,start:Int,count:Int):Long=(0 until count).fold(0L){v,i->v or (((data[(start+i)/8].toLong() ushr ((start+i)%8)) and 1) shl i)}
    private fun parity(value:Long)=java.lang.Long.bitCount(value) and 1
    private fun transfer(ap:Boolean,read:Boolean,address:Int,value:Long=0):Long {
        try{return transferChecked(ap,read,address,value)}catch(error:Exception){invalidateCaches();throw error}
    }
    private fun transferChecked(ap:Boolean,read:Boolean,address:Int,value:Long):Long {
        if(overrun==null&&!ap&&!(read&&address in listOf(0,4))&&!(!read&&address==0))dpRead(4)
        if((ap||read&&address==12)&&!ready)throw IOException("Programming AP requires verified ORUN mode")
        var request=0x81 or(if(ap)2 else 0) or(if(read)4 else 0) or((address and 12) shl 1)
        request=request or((Integer.bitCount((request ushr 1) and 15) and 1) shl 5)
        repeat(8){attempt->
            val direction=BooleanArray(if(read)54 else 12){it<8||read&&it>=46}
            val reply=clocks(direction,BooleanArray(direction.size){it<8&&(request ushr it) and 1==1})
            val ack=bits(reply,8,3).toInt()
            if(!read&&ack in listOf(1,2,4)){
                val n=if(ack==1||overrun==true)42 else 9
                val output=BooleanArray(n)
                if(ack==1){repeat(32){output[it+1]=(value ushr it) and 1==1L};output[33]=parity(value)==1}
                clocks(BooleanArray(n){it!=0},output)
            }
            when(ack){
                1->{if(!read)return 0;val data=bits(reply,11,32);if(bits(reply,43,1).toInt()!=parity(data))throw IOException("Programming SWD parity mismatch");return data}
                2->{if(attempt==7)throw IOException("Programming SWD WAIT limit");if(overrun==true){if(!ap&&!read&&address==0)throw IOException("ABORT unexpectedly WAITed");transfer(false,false,0,0x1e)}}
                4->throw IOException("Programming SWD FAULT; no unlock fallback")
                else->throw IOException("Programming SWD invalid ACK $ack")
            }
        }
        throw IOException("Programming SWD WAIT limit")
    }
    private fun dpRead(at:Int):Long=transfer(false,true,at).also{if(at==4){overrun=it and 1!=0L;if(overrun!=true)ready=false}}
    private fun dpWrite(at:Int,value:Long){require(at==0&&value==0x1eL||at==4&&value in setOf(1L,0x50000001L)||at==8&&value in listOf(0L,0xf0L));transfer(false,false,at,value);if(at==8)selectedBank=value}
    private fun select(bank:Long){if(selectedBank!=bank)dpWrite(8,bank)}
    private fun apRead(at:Int):Long {select((at and 0xf0).toLong());transfer(true,true,at and 12);return dpRead(12)}
    private fun apWrite(at:Int,value:Long){require(at in listOf(0,4,12));select(0);transfer(true,false,at,value);dpRead(12);status();if(at==0)configuredCsw=value}
    private fun ensureCsw(){if(configuredCsw!=csw)apWrite(0,csw)}
    private fun status(){if(dpRead(4) and 0xa2L!=0L){invalidateCaches();throw IOException("Programming debug access error")}}
    private fun configure(){
        ready=false;invalidateCaches();dpRead(4);dpWrite(0,0x1e);dpWrite(8,0);dpWrite(4,0x50000001)
        var powered=false;repeat(20){if(!powered){val s=dpRead(4);if(s and 1==0L)throw IOException("ORUN mode not accepted");powered=s and 0xa0000000L==0xa0000000L}}
        if(!powered)throw IOException("Programming debug power timeout");ready=true
        val id=apRead(0xfc);if(id and 15!=1L||(id ushr 13) and 15!=8L)throw IOException("Unsupported programming AP0")
        val initial=apRead(0);if(initial and 0x40==0L)throw IOException("Memory access disabled; no recovery permitted")
        csw=(initial and 0xffffffc8L) or 0x12L;apWrite(0,csw)
    }
    fun initialize(){
        ready=false;overrun=null;invalidateCaches()
        if(query(0xe8) and (1L shl 17)==0L||query(0xc7,0xff) and 2==0L)throw IOException("Unsupported J-Link SWD probe")
        query(0xc7,1);if(query(0xc7,0xfe)!=1L)throw IOException("J-Link SWD selection failed")
        send(byteArrayOf(5,0xe8.toByte(),3)) // 1000kHz; identity/geometry are checked before mutation.
        val data=BooleanArray(136);repeat(56){data[it]=true;data[it+72]=true};repeat(16){data[it+56]=(0xe79e ushr it) and 1==1}
        clocks(BooleanArray(136){true},data)
        if(dpRead(0)!=0x2ba01477L)throw IOException("Unsupported programming DPIDR")
        configure()
    }
    private fun readSpan(address:Long,length:Int){
        require(address>=0&&address%4==0L&&length in 4..512&&length%4==0&&address%1024+length<=1024)
        val memory=address+length<=0x100000L||address>=0x10000000L&&address+length<=0x10002000L
        val register=length==4&&address in setOf(0xe000edf0L,0xe000edf8L,0xe000edfcL,0xe000ed0cL,0x4001e400L,0x4001e504L,0x40010400L,0x40010504L,0x40010508L,0x4001050cL)||address==0x40010504L&&length==12
        val flashPermissions=length==12&&address in 0x4001e800L..0x4001e870L&&(address-0x4001e800L)%16==0L
        require(memory||register||flashPermissions){"Programming read address is not allowed"}
    }
    private data class Access(val ap:Boolean,val read:Boolean,val address:Int,val value:Long=0)
    private class QueuedWait:IOException("Programming queued SWD WAIT; no write replay")
    /** ORUN fixes the data-phase length even on WAIT/FAULT (ADIv5 B4).
     * A packet contains at most ONE FLASH write; all later accesses only
     * complete it and observe READY. A failed write is never retried. */
    private fun queue(accesses:List<Access>):LongArray {
        require(ready&&overrun==true&&accesses.size in 1..129)
        val direction=BooleanArray(accesses.size*54);val output=BooleanArray(direction.size)
        accesses.forEachIndexed{index,a->
            val at=index*54;var request=0x81 or(if(a.ap)2 else 0) or(if(a.read)4 else 0) or((a.address and 12) shl 1)
            request=request or((Integer.bitCount((request ushr 1) and 15) and 1) shl 5)
            for(bit in 0 until 54){direction[at+bit]=bit<8||bit>=if(a.read)46 else 13
                if(bit<8)output[at+bit]=(request ushr bit) and 1==1
                else if(!a.read&&bit in 13..44)output[at+bit]=(a.value ushr(bit-13)) and 1L==1L
                else if(!a.read&&bit==45)output[at+bit]=parity(a.value)==1}
        }
        try{
            val reply=clocks(direction,output);val values=LongArray(accesses.size)
            accesses.forEachIndexed{index,a->val at=index*54
                when(val ack=bits(reply,at+8,3).toInt()){
                    1->if(a.read){val value=bits(reply,at+11,32);if(bits(reply,at+43,1).toInt()!=parity(value))throw IOException("Programming queued SWD parity mismatch");values[index]=value}
                    2->throw QueuedWait()
                    4->throw IOException("Programming queued SWD FAULT; no write replay")
                    else->throw IOException("Programming queued SWD invalid ACK $ack")
                }
            }
            require(values.last() and 0xa3L==1L){"Programming debug access error or ORUN lost"}
            return values
        }catch(error:Exception){invalidateCaches();throw error}
    }
    fun readWords(address:Long,length:Int):ByteArray {
        readSpan(address,length);require(ready);val result=ByteArray(length);var offset=0
        // 124 words + TAR/completion/final/status fits the probe's packet.
        while(offset<length){val size=minOf(496,length-offset);var complete=false
            for(attempt in 0..2){
                ensureCsw();select(0)
                val accesses=mutableListOf(Access(true,false,4,address+offset),Access(false,true,12))
                repeat(size/4){accesses+=Access(true,true,12)}
                accesses+=Access(false,true,12);accesses+=Access(false,true,4)
                try{val values=queue(accesses)
                    for(i in 0 until size)result[offset+i]=(values[3+i/4] ushr((i%4)*8)).toByte()
                    complete=true;break
                }catch(wait:QueuedWait){
                    if(attempt==2)throw wait
                    clocks(BooleanArray(64){true},BooleanArray(64){it<56});ready=false;invalidateCaches()
                    if(dpRead(0)!=0x2ba01477L)throw IOException("Programming DPIDR changed after synchronization")
                    configure()
                }
            }
            check(complete);offset+=size
        };return result
    }
    fun programFlashWordAndReady(address:Int,data:ByteArray):Boolean {
        require(address in 0..0xffffc&&address%4==0&&data.size==4)
        ensureCsw();select(0)
        val values=queue(listOf(Access(true,false,4,address.toLong()),Access(false,true,12),
            Access(true,false,12,bits(data,0,32)),Access(false,true,12),
            Access(true,false,4,0x4001e400L),Access(false,true,12),
            Access(true,true,12),Access(false,true,12),Access(false,true,4)))
        return values[7]==1L
    }
    private fun writeWord(address:Long,value:Long){
        require(value in 0..0xffffffffL)
        try{ensureCsw();select(0);queue(listOf(Access(true,false,4,address),Access(false,true,12),Access(true,false,12,value),Access(false,true,12),Access(false,true,4)))}
        catch(error:Exception){throw IOException("Write 0x%08x: %s".format(address,error.message?:error.javaClass.simpleName),error)}
    }
    fun writeDebugControl(value:Long){require(value in setOf(0xa05f0000L,0xa05f0001L,0xa05f0003L));writeWord(0xe000edf0L,value)}
    /** DCRSR REGWnR stays zero: READ PC(0x0f), xPSR(0x10), MSP(0x11).
     * No general core-register write/PSP selector is available. Primary table:
     * https://dev.ti.com/tirex/content/simplelink_cc13x0_sdk_2_20_00_38/docs/driverlib_cc13xx_cc26xx/cc13x2_cc26x2_v1/register_descriptions/CPU_MMAP/CPU_SCS.html
     * NXP AN11553 section9.1.3 independently gives the same ARM REGSEL mapping.
     * DCRSR completion clears S_REGRDY until DCRDR is valid. */
    fun readCoreRegister(selector:Int):Long {
        require(selector in setOf(0x0f,0x10,0x11))
        require(bits(readWords(0xe000edf0L,4),0,32) and 0x20001L==0x20001L){"Core register read requires halted debug"}
        writeWord(0xe000edf4L,selector.toLong())
        val start=now()
        repeat(128){if(bits(readWords(0xe000edf0L,4),0,32) and 0x10000L!=0L)return bits(readWords(0xe000edf8L,4),0,32)
            if(now()-start>=500_000_000)throw IOException("Core register S_REGRDY timed out")}
        throw IOException("Core register S_REGRDY polling limit")
    }
    /** ARMv7-M reset vector catch, not a release of the previous PC:
     * https://documentation-service.arm.com/static/5fce431be167456a35b36ade
     * CMSIS core_cm4.h defines DHCSR/DEMCR and SYSRESETREQ's preserved PRIGROUP.
     * Caller must supply the separate explicit reset-catch capability. */
    fun enableResetVectorCatch(){
        check(originalDemcr==null);val before=bits(readWords(0xe000edfcL,4),0,32);originalDemcr=before
        writeWord(0xe000edfcL,before or 1L)
        require(bits(readWords(0xe000edfcL,4),0,32)==before or 1L){"Reset vector catch not enabled"}
    }
    fun requestCaughtSystemReset(){
        check(originalDemcr!=null)
        require(bits(readWords(0xe000edfcL,4),0,32) and 1L!=0L&&bits(readWords(0xe000edf0L,4),0,32) and 1L!=0L)
        val priority=bits(readWords(0xe000ed0cL,4),0,32) and 0x700L
        try{writeWord(0xe000ed0cL,0x05fa0004L or priority)}finally{invalidateCaches()}
    }
    fun restoreResetVectorCatch(){
        val before=checkNotNull(originalDemcr);writeWord(0xe000edfcL,before)
        require(bits(readWords(0xe000edfcL,4),0,32)==before){"Reset vector catch restoration failed"};originalDemcr=null
    }
    /** Explicit normal firmware start ends this app's debug catch session.
     * Preserve every other DEMCR bit, even if VC_CORERESET was set on entry. */
    fun finishResetVectorCatchForNormalStart(){
        val normal=checkNotNull(originalDemcr) and 1L.inv();writeWord(0xe000edfcL,normal)
        require(bits(readWords(0xe000edfcL,4),0,32)==normal){"Normal-start reset catch clear failed"};originalDemcr=null
    }
    /** Nordic DIF: USB close alone does not end Debug Interface mode. After
     * explicit normal CPU release, drop both power requests and confirm only
     * through DP (no more AP/UID traffic is allowed after this point).
     * https://docs.nordicsemi.com/r/bundle/ps_nrf52840/page/dif.html */
    fun endNormalDebugSession(){
        ready=false;invalidateCaches();dpWrite(4,1)
        require(dpRead(4) and 0x50000000L==0L){"Debug power requests did not clear; start state is uncertain"}
        ready=false;invalidateCaches()
    }
    fun setNvmcMode(mode:Int){require(mode in 0..2);writeWord(0x4001e504L,mode.toLong())}
    fun eraseFlashPage(address:Int){require(address in 0..0xff000&&address%4096==0);writeWord(0x4001e508L,address.toLong())}
    fun programFlashWords(address:Int,data:ByteArray){
        require(address>=0&&address%4==0&&data.size in 4..256&&data.size%4==0&&address<=0x100000-data.size&&address/4096==(address+data.size-1)/4096&&address%1024+data.size<=1024)
        ensureCsw();apWrite(4,address.toLong())
        for(i in data.indices step 4)try{apWrite(12,bits(data,i*8,32))}
            catch(error:Exception){throw IOException("Programming FLASH 0x%08x: %s".format(address+i,error.message?:error.javaClass.simpleName),error)}
    }
}
