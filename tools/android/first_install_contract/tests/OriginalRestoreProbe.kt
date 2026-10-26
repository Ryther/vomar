package org.openvimar.installer

import java.nio.file.Files
import java.nio.file.Path

internal fun originalRestoreProbe(args:Array<String>){
    val original=OriginalArchive.verify(Files.readAllBytes(Path.of(args[1])))
    val scenario=args[3];val uid=original.identity
    val plan=OriginalRestorePlan.review(original,"ef1faf4b-cd24-42c7-8508-8d51b4f10ad5",77)
    val flash=ByteArray(AnchorV1.FLASH){0x55};val uicr=original.uicr();val ficr=original.ficr()
    if(scenario=="wrong-uicr")uicr[0]=0
    if(scenario=="wrong-ficr")ficr[0]=0
    var cancelled=false;val erases=mutableListOf<Int>();val progress=mutableListOf<Int>();var closed=0
    val journal=FileInstallJournal(Path.of(args[2],"restore"),originalRestore=true)
    val session=object:AuthorizedSwdSession {
        override val binding=plan.binding
        override val generation=if(scenario=="wrong-generation")78L else 77L
        override fun check(expectedGeneration:Long,expectedIdentity:TargetIdentity){check(expectedGeneration==generation&&expectedIdentity==uid)}
        override fun readIdentity()=if(scenario=="wrong-uid")uid.copy(uid0=uid.uid0 xor 1)else uid
        override fun readFicr()=ficr.copyOf()
        override fun readUicr()=uicr.copyOf()
        override fun readFlash(address:Int,size:Int)=flash.copyOfRange(address,address+size)
        override fun erasePage(address:Int,expectedGeneration:Long){check(journal.load(binding.id)?.phase==InstallPhase.PAGE_ERASE_INTENT);erases+=address;flash.fill(0xff.toByte(),address,address+4096);if(scenario=="cancel")cancelled=true}
        override fun program(address:Int,data:ByteArray,expectedGeneration:Long){check(journal.load(binding.id)?.phase==InstallPhase.PAGE_WRITE_INTENT);data.copyInto(flash,address);if(scenario=="readback")flash[address]=(flash[address].toInt() xor 1).toByte()}
        override fun close(){closed++}
    }
    val outcome=OriginalRestoreEngine().run(plan,object:SwdAuthorizer{override fun acquire(binding:InstallBinding)=session},journal,
        onProgress={done,total->check(total==2*AnchorV1.FLASH);check(progress.isEmpty()||done>progress.last());progress+=done},checkCancelled={check(!cancelled){"Cancelled"}})
    check(closed==1)
    if(scenario=="good"){
        check(outcome.verified){outcome.toString()};check(flash.contentEquals(original.flash()));check(erases.size==256&&erases.last()==0&&erases.first()==4096)
        check(progress.last()==2*AnchorV1.FLASH);check(journal.load(plan.binding.id)?.phase==InstallPhase.VERIFIED)
        check(!OriginalRestoreEngine().run(plan,object:SwdAuthorizer{override fun acquire(binding:InstallBinding):AuthorizedSwdSession=error("Reused grant opened transport")},journal).verified)
    }else{check(!outcome.verified);if(scenario.startsWith("wrong-"))check(erases.isEmpty());if(scenario=="cancel")check(erases==listOf(4096))}
    check(uicr.contentEquals(if(scenario=="wrong-uicr")original.uicr().apply{this[0]=0}else original.uicr()))
}
