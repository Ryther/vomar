package org.openvimar.installer

import java.nio.file.Files
import java.nio.file.Path
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec

/** Stateful separate FLASH/FICR/UICR model, not a packet expectation mock. */
internal fun engineProbe(args:Array<String>) {
    val original=OriginalArchive.verify(Files.readAllBytes(Path.of(args[1])))
    val exported=OriginalArchive.exportAndReopen(original,object:ArchiveExport {
        override fun create(bytes:ByteArray):String {Files.write(Path.of(args[5],"export.zip"),bytes);return Path.of(args[5],"export.zip").toString()}
        override fun reopen(document:String)=Files.readAllBytes(Path.of(document))
    })
    val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(Files.readAllBytes(Path.of(args[3]))))
    val scenario=args[4]
    val rawRelease=Files.readAllBytes(Path.of(args[2]))
    val material=exported.deriveOriginal()
    val plan=if(scenario.startsWith("bench-")){
        val candidate=CandidateRelease.inspect(rawRelease,key,"0.5.0");val request="ef1faf4b-cd24-42c7-8508-8d51b4f10ad5"
        candidate.preparePlan(material,candidate.reviewOneBench(material.identity,request,77,candidate.releaseSha256),request,77)
    }else InstallPlan.prepare(material,CommonRelease.verify(rawRelease,key,"0.5.0"))
    val disk=if(scenario in setOf("file-backed","file-after-commit-intent"))FileInstallJournal(Path.of(args[5],"journal")) else null
    var step=0;var mutationCount=0;var closes=0;var finalCommit=false;var journal:InstallJournalRecord?=null
    if(args[4]=="existing-journal")journal=InstallJournalRecord(plan.binding,100,InstallPhase.COMMIT_INTENT,0xb0fc,true,true)
    var actualUid=material.identity
    val flash=original.flash();val uicr=original.uicr();val ficr=original.ficr();val trace=mutableListOf<String>()
    if(scenario=="changed-original")flash[0xf1234]=0
    if(scenario=="changed-uicr")uicr[0]=0
    if(scenario=="changed-uid")actualUid=actualUid.copy(uid0=actualUid.uid0 xor 1)
    var leaseEpoch=if(scenario=="bench-wrong-generation")78L else 77L;var cancellation=false
    val fail=scenario.removePrefix("fail-").toIntOrNull()
    fun event(name:String) {trace+=name;step++;if(step==fail)error("Injected event $step: $name")}
    val port=object:AuthorizedSwdSession {
        override val binding=if(scenario=="wrong-authorization")plan.binding.copy(archiveSha256="00".repeat(32)) else plan.binding
        override val generation get()=leaseEpoch
        override fun check(expectedGeneration:Long,expectedIdentity:TargetIdentity) {
            event("lease");check(leaseEpoch==expectedGeneration&&actualUid==expectedIdentity){"Lease generation or target changed"}
        }
        override fun readIdentity():TargetIdentity {event("identity");return actualUid}
        override fun readFicr():ByteArray {event("ficr");return ficr.copyOf()}
        override fun readUicr():ByteArray {event("uicr");return uicr.copyOf()}
        override fun readFlash(address:Int,size:Int):ByteArray {
            event("read:$address:$size");check(address>=0&&address<=flash.size-size);return flash.copyOfRange(address,address+size)
        }
        override fun erasePage(address:Int,expectedGeneration:Long) {
            event("erase:$address");check(expectedGeneration==leaseEpoch&&address%4096==0&&address in 0 until 0x100000)
            check(journal?.phase==InstallPhase.PAGE_ERASE_INTENT&&journal?.address==address)
            check(journal?.mutationMayHaveStarted==true){"Durable erase intent must retain possible mutation after a crash"}
            check(!finalCommit);mutationCount++;flash.fill(0xff.toByte(),address,address+4096)
            if(scenario=="cancel-page")cancellation=true
        }
        override fun program(address:Int,data:ByteArray,expectedGeneration:Long) {
            event("program:$address:${data.size}");check(expectedGeneration==leaseEpoch)
            check(address>=0&&address%4==0&&data.size%4==0&&data.size in 4..256&&address<=0x100000-data.size&&address/4096==(address+data.size-1)/4096)
            check(!finalCommit)
            val isCommit=address==0xb0fc&&data.size==4
            if(isCommit){check(journal?.phase==InstallPhase.COMMIT_INTENT&&journal?.commitMayHaveBeenWritten==true);check(word(data,0)==0xa60c17edL);finalCommit=true}
            else {
                check(journal?.phase==InstallPhase.PAGE_WRITE_INTENT&&journal?.address==address)
                if(address<0xb100&&address+data.size>0xb0fc)for(i in data.indices)if(address+i in 0xb0fc..0xb0ff)check(data[i]==0xff.toByte())
            }
            mutationCount++
            for(i in data.indices){check((flash[address+i].toInt() and data[i].toInt())==data[i].toInt());flash[address+i]=data[i]}
            if(scenario=="generation-batch"&&!isCommit)leaseEpoch++
            if(scenario=="uid-batch"&&!isCommit)actualUid=actualUid.copy(uid1=actualUid.uid1 xor 1)
            if(scenario=="lost-commit"&&isCommit)error("Commit acknowledgement lost after programming")
            if(scenario=="corrupt-readback"&&!isCommit)flash[address]=(flash[address].toInt() xor 1).toByte()
        }
        override fun close(){event("close");closes++}
    }
    val store=object:InstallJournalStore {
        override fun load(bindingId:String):InstallJournalRecord? {event("load-journal");if(scenario=="unreadable-journal")error("Journal read failed");if(disk!=null)journal=disk.load(bindingId);return journal}
        override fun begin(record:InstallJournalRecord):Boolean {event("begin-journal");if(journal!=null)return false;if(disk!=null&&!disk.begin(record))return false;journal=record;return true}
        override fun save(record:InstallJournalRecord) {
            event("journal:${record.phase}");disk?.save(record);journal=record
            if(scenario in setOf("journal-after-commit-intent","file-after-commit-intent")&&record.phase==InstallPhase.COMMIT_INTENT)error("Intent was saved but its acknowledgement failed")
        }
    }
    val outcome=FirstInstallEngine().run(plan,object:SwdAuthorizer {
        override fun acquire(binding:InstallBinding):AuthorizedSwdSession {event("acquire");check(binding==plan.binding);return port}
    },store){check(!cancellation){"Cancelled explicitly"}}
    if(scenario in setOf("good","file-backed","bench-good")) {
        check(outcome.verified&&journal?.phase==InstallPhase.VERIFIED&&finalCommit&&closes==1){outcome.toString()}
        check(flash.contentEquals(plan.finalImage())&&uicr.contentEquals(original.uicr()))
        check(trace.takeLast(2)==listOf("close","journal:VERIFIED"))
        val copy=plan.finalImage();copy.fill(0);check(sha256(plan.finalImage())==plan.binding.installedSha256)
    } else {
        check(!outcome.verified)
        if(scenario in setOf("changed-original","changed-uicr","changed-uid","wrong-authorization"))check(mutationCount==0)
        if(scenario=="cancel-page")check(mutationCount==1)
        if(scenario in setOf("generation-batch","uid-batch"))check(mutationCount<=2)
        if(scenario in setOf("lost-commit","journal-after-commit-intent","file-after-commit-intent"))check(outcome.commitMayHaveBeenWritten&&journal?.phase!=InstallPhase.VERIFIED)
        if(scenario=="existing-journal")check(mutationCount==0&&outcome.commitMayHaveBeenWritten&&outcome.mutationMayHaveStarted&&journal?.phase==InstallPhase.COMMIT_INTENT&&journal?.sequence==100&&journal?.commitMayHaveBeenWritten==true)
        if(scenario=="unreadable-journal")check(mutationCount==0&&outcome.journalFailure&&journal==null)
        if(scenario=="bench-wrong-generation")check(mutationCount==0&&trace.none{it=="identity"||it=="ficr"||it.startsWith("read:")})
    }
    Files.writeString(Path.of(args[5],"result.txt"),"${outcome.verified} $mutationCount $step ${outcome.commitMayHaveBeenWritten}\n")
    Files.write(Path.of(args[5],"trace.txt"),trace)
    Files.write(Path.of(args[5],"anchor.bin"),material.anchor())
    Files.write(Path.of(args[5],"table.bin"),material.table())
}
