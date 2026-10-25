package org.openvimar.updater

import org.openvimar.installer.*
import org.openvimar.installer.resume.*
import org.openvimar.updater.installer.*
import java.nio.file.Files
import java.nio.file.Path
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec
import java.time.Instant

internal fun resumeLeaseProbe(args:Array<String>){
 val directory=Path.of(args[3]);val scenario=args[0];val target=ProgrammingWireTarget();target.logLimit=10000
 byteArrayOf(0,0,2,0x20,1,0x10,0,0).copyInto(target.flash)
 val token=checkNotNull(DkUsbOperationGate.acquire("synthetic explicit resume"));val wire=JlinkInstallWire(target,{token.checkCurrent()});wire.initialize()
 val ficr=ByteArray(4096);for(at in ficr.indices step 512)wire.readWords(0x10000000L+at,512).copyInto(ficr,at)
 val regions=mapOf("flash.bin" to target.flash.copyOf(),"ficr.bin" to ficr,"uicr.bin" to ByteArray(4096){0xff.toByte()})
 val raw=QuiescentArchive.create(regions,regions,QuiescentProvenance("synthetic","synthetic",3300,0x1366,0x1060,4,0x85,3),Instant.parse("2026-10-23T12:00:00Z"),Instant.parse("2026-10-23T12:01:00Z"),0,false)
 val original=OriginalArchive.verify(raw);val material=OriginalArchive.exportAndReopen(original,object:ArchiveExport{override fun create(bytes:ByteArray)="content://initial/original";override fun reopen(document:String)=raw}).deriveOriginal()
 val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(Files.readAllBytes(Path.of(args[2]))));val candidate=CandidateRelease.inspect(Files.readAllBytes(Path.of(args[1])),key,"9.0.0")
 val request="ef1faf4b-cd24-42c7-8508-8d51b4f10ad5";val plan=candidate.preparePlan(material,candidate.reviewOneBench(material.identity,request,token.generation,candidate.releaseSha256),request,token.generation)
 val base=FileInstallJournal(directory.resolve("transactions"));check(base.begin(InstallJournalRecord(plan.binding,1,InstallPhase.PREPARED,null,false,false)))
 // Includes PREPARED/false base: resume HALT retention is unconditional.
 val receipt=OriginalExportReceipt.fromVerifiedExport(material,plan.binding);val reopened=ResumeOriginal.reopen(original,receipt,"content://cloud/copy"){raw}
 val journal=FileResumeJournal(directory.resolve("transactions"),directory.resolve("resume"));val checkpoint=journal.inspect(plan.binding,receipt)
 val reviewed=ReviewedResume.review(plan,reopened,journal,checkpoint.headSha256,request,token.generation)
 target.mode=if(scenario=="resume-mode2")2 else 1
 if(scenario=="resume-bad-uicr")target.corruptUicr=true
 if(scenario=="resume-unconfirmed")target.uid0=target.uid0 xor 1
 var cancelled=false
 target.onMemoryWrite={address,value->
  if(scenario=="resume-cancel"&&address==0xe000edf0L&&value and 3==3L)cancelled=true
  if(scenario=="resume-mode-ack-loss"&&address==0x4001e504L&&value==0L)target.corruptReadParityCount=1
 }
 val lease=NrfInitialInstallLease(wire,token,{cancelled})
 val result=runCatching{lease.openForResume(material.identity,reviewed.hardwareAuthority())}
 val good=scenario in setOf("resume-mode1","resume-mode2");check(result.isSuccess==good){result.toString()}
 lease.finish();if(scenario=="resume-unconfirmed"){check(!target.halted&&!lease.haltConfirmed&&target.memoryWrites.isEmpty());token.close();return}
 check(target.halted&&lease.haltRetentionRequired&&lease.haltConfirmed)
 check(target.memoryWrites.none{it.first in 0L..0xfffffL||it.first==0x4001e508L||it.first in 0x10001000L..0x10001fffL})
 if(good)check(target.mode==0&&target.memoryWrites.count{it.first==0x4001e504L&&it.second==0L}==1)
 if(scenario=="resume-bad-uicr")check(target.memoryWrites.none{it.first==0x4001e504L})
 check(target.memoryWrites.none{it.first==0xe000edf0L&&it.second and 2==0L});token.close()
}
