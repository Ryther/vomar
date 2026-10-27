package org.openvimar.installer.resume

import org.openvimar.installer.*
import java.nio.file.Files
import java.nio.file.Path
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec

internal fun resumeEngineProbe(args:Array<String>){
 val directory=Path.of(args[4]);val scenario=args[5];val raw=Files.readAllBytes(Path.of(args[1]));val original=OriginalArchive.verify(raw)
 val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(Files.readAllBytes(Path.of(args[3]))));val candidate=CandidateRelease.inspect(Files.readAllBytes(Path.of(args[2])),key,"9.0.0")
 var exported=byteArrayOf();val material=OriginalArchive.exportAndReopen(original,object:ArchiveExport{override fun create(bytes:ByteArray):String{exported=bytes;return "content://initial/original"};override fun reopen(document:String)=exported}).deriveOriginal()
 var epoch=77L;var request="ef1faf4b-cd24-42c7-8508-8d51b4f10ad5"
 fun plan()=candidate.preparePlan(material,candidate.reviewOneBench(material.identity,request,epoch,candidate.releaseSha256),request,epoch)
 val initialPlan=plan();val binding=initialPlan.binding;val receipt=OriginalExportReceipt.fromVerifiedExport(material,binding)
 val reopened=ResumeOriginal.reopen(original,receipt,"content://cloud/moved"){raw}
 val baseDir=directory.resolve("base");val initialJournal=FileInstallJournal(baseDir);check(initialJournal.begin(InstallJournalRecord(binding,1,InstallPhase.PREPARED,null,false,false)))
 val all=scenario in setOf("body-ready","body-short-frontier","body-short-frontier-lost","body-short-frontier-tail","committed","lost-commit","one-damaged-page")
 if(scenario in setOf("stale-prepared","replay-prepared"))Unit
 else if(scenario.startsWith("body-short-frontier"))initialJournal.save(InstallJournalRecord(binding,2,InstallPhase.PAGE_WRITE_INTENT,0xef000,true,false))
 else if(all)initialJournal.save(InstallJournalRecord(binding,2,InstallPhase.COMMIT_INTENT,0xb0fc,true,true))
 else initialJournal.save(InstallJournalRecord(binding,2,InstallPhase.PAGE_WRITE_INTENT,0x18000,true,false))
 val flash=if(all)initialPlan.finalImage().also{if(scenario!="committed")repeat(4){n->it[0xb0fc+n]=0xff.toByte()}} else original.flash().also{if(scenario!="replay-prepared")it.fill(0,0,0x19000)}
 if(scenario=="one-damaged-page")flash[0x18000]=(flash[0x18000].toInt() xor 1).toByte()
 val erased=mutableListOf<Int>()
 val ficr=original.ficr();val uicr=original.uicr();var uid=material.identity;var cancellation=false;var mutations=0;var closes=0;var failedFirst=false
 if(scenario=="unissued-changed")flash[0x1a123]=(flash[0x1a123].toInt() xor 1).toByte()
 if(scenario=="uicr")uicr[0]=(uicr[0].toInt() xor 1).toByte()
 if(scenario=="uid")uid=uid.copy(uid1=uid.uid1 xor 1)
 if(scenario=="cancel-prior")cancellation=true
 val store=FileResumeJournal(baseDir,directory.resolve("resume"))
 fun reviewed(p:InstallPlan=plan()):ReviewedResume{val head=store.inspect(binding,receipt);return ReviewedResume.review(p,reopened,store,head.headSha256,request,epoch)}
 val review=reviewed(initialPlan)
 if(scenario in setOf("stale-head","stale-prepared"))store.acquire(binding,receipt,review.journalHeadSha256,request,epoch,"content://cloud/moved").use{s->s.append(ResumePhase.REVIEWED,null,s.checkpoint.frontierPage,s.checkpoint.commitPossible);if(scenario=="stale-prepared"){s.append(ResumePhase.ERASE_INTENT,0,0,false)}}
 val port=object:AuthorizedSwdSession{
  override val binding=binding
  override val generation get()=epoch+if(scenario=="wrong-generation")1 else 0
  override fun check(expectedGeneration:Long,expectedIdentity:TargetIdentity){check(expectedGeneration==generation&&uid==expectedIdentity)}
  override fun readIdentity()=uid
  override fun readFicr()=ficr.copyOf()
  override fun readUicr()=uicr.copyOf()
  override fun readFlash(address:Int,size:Int)=flash.copyOfRange(address,address+size)
  fun intent(phase:ResumePhase,address:Int){val files=Files.list(directory.resolve("resume").resolve(binding.id)).use{s->s.filter{it.fileName.toString().endsWith(".json")}.sorted().toArray()};val m=obj(StrictJson.parse(Files.readAllBytes(files.last() as Path)));check(m["phase"]==phase.name&&m["address"]==address.toLong())}
  override fun erasePage(address:Int,expectedGeneration:Long){check(expectedGeneration==epoch);intent(ResumePhase.ERASE_INTENT,address);mutations++;erased+=address;flash.fill(0xff.toByte(),address,address+4096);if(scenario in setOf("cancel-after","replay-prepared"))cancellation=true}
  override fun program(address:Int,data:ByteArray,expectedGeneration:Long){check(expectedGeneration==epoch);intent(if(address==0xb0fc&&data.size==4)ResumePhase.COMMIT_INTENT else ResumePhase.WRITE_INTENT,address);mutations++;for(i in data.indices){check(flash[address+i].toInt() and data[i].toInt()==data[i].toInt());flash[address+i]=data[i]}
   if(scenario=="generation")epoch++
   if(scenario=="resume-again"&&!failedFirst){failedFirst=true;error("Process/ACK loss after partial page zero programming")}
   if((scenario=="lost-commit"||scenario in setOf("body-short-frontier-lost","body-short-frontier-tail"))&&address==0xb0fc)error("Lost commit ACK")
  }
  override fun close(){closes++}
 }
 val authorizer=object:SwdAuthorizer{override fun acquire(binding:InstallBinding):AuthorizedSwdSession{check(binding==port.binding);return port}}
 val measured=mutableMapOf<String,Int>()
 var result=ExplicitResumeEngine().runWithProgress(review,authorizer,onProgress={label,done,total->
  check(total==AnchorV1.FLASH&&done in 4096..total);check(done>(measured[label]?:0));measured[label]=done
 }){check(!cancellation){"Cancelled"}}
 if(scenario in setOf("good","body-ready","body-short-frontier","committed"))check(measured["Final verification"]==AnchorV1.FLASH)
 if(scenario=="replay-prepared"){
  check(!result.outcome.verified&&mutations==1);cancellation=false
  result=ExplicitResumeEngine().run(review,authorizer);check(mutations==1&&result.outcome.mutationMayHaveStarted&&result.outcome.commitMayHaveBeenWritten)
 }
 if(scenario in setOf("body-short-frontier-lost","body-short-frontier-tail")){
  check(!result.outcome.verified&&mutations==1&&store.inspect(binding,receipt).frontierPage==0xef000)
  epoch=78;request="00000000-0000-0000-0000-000000000001"
  if(scenario=="body-short-frontier-tail")flash[0xf1234]=0
  result=ExplicitResumeEngine().run(reviewed(),authorizer)
  check(mutations==1&&store.inspect(binding,receipt).frontierPage==0xef000)
 }
 if(scenario=="resume-again"){
  check(!result.outcome.verified&&store.inspect(binding,receipt).frontierPage==0x18000);epoch=78;request="00000000-0000-0000-0000-000000000001"
  result=ExplicitResumeEngine().run(reviewed(),authorizer)
 }
 val expectedGood=scenario in setOf("good","body-ready","body-short-frontier","body-short-frontier-lost","committed","resume-again","one-damaged-page")
 check(result.outcome.verified==expectedGood){result.toString()}
 check(result.outcome.mutationMayHaveStarted) // inherited uncertainty survives every early refusal/cancel
 if(expectedGood)check(flash.contentEquals(initialPlan.finalImage())&&uicr.contentEquals(original.uicr()))
 if(scenario in setOf("body-ready","body-short-frontier"))check(mutations==1&&result.mode==ResumeMode.COMMIT_ONLY)
 if(scenario=="one-damaged-page")check(erased==listOf(0x18000)){"Repair unnecessarily erased ${erased.size} pages: $erased"}
 if(scenario=="committed")check(mutations==0&&result.mode==ResumeMode.VERIFY_ONLY)
 if(scenario in setOf("unissued-changed","uicr","uid","cancel-prior","wrong-generation","stale-head","stale-prepared"))check(mutations==0)
 if(scenario=="cancel-after")check(mutations==1)
 if(scenario=="generation")check(mutations<=2)
 if(scenario in setOf("lost-commit","stale-prepared"))check(result.outcome.commitMayHaveBeenWritten)
 Files.writeString(directory.resolve("result.txt"),"${result.outcome.verified} $mutations ${result.mode} ${result.outcome.mutationMayHaveStarted}\n")
}
