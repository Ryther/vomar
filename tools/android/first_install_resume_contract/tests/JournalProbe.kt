package org.openvimar.installer.resume

import org.openvimar.installer.*
import java.nio.file.Files
import java.nio.file.Path

internal fun journalProbe(directory:Path,scenario:String){
 val binding=InstallBinding(TargetIdentity(1,2,0x41414430),"11".repeat(32),"22".repeat(32),"33".repeat(32),"44".repeat(32),"55".repeat(32),"66".repeat(32),"77".repeat(32))
 val baseDirectory=directory.resolve("base");val base=FileInstallJournal(baseDirectory)
 check(base.begin(InstallJournalRecord(binding,1,InstallPhase.PREPARED,null,false,false)))
 base.save(InstallJournalRecord(binding,2,InstallPhase.PAGE_ERASE_INTENT,0x18000,true,false))
 base.save(InstallJournalRecord(binding,3,InstallPhase.FAILED,0x18000,true,false,InstallPhase.PAGE_ERASE_INTENT,"lost connection"))
 val receipt=OriginalExportReceipt.parse(("{\"archiveSha256\":\"${binding.archiveSha256}\",\"bindingId\":\"${binding.id}\",\"document\":\"content://initial/export\",\"schemaVersion\":1}\n").toByteArray())
 val syncEvents=mutableListOf<Path>()
 val journal=if(scenario in setOf("durability","durability-fail"))FileResumeJournal(baseDirectory,directory.resolve("resume")){path->
  syncEvents.add(path);if(scenario=="durability-fail"&&path==directory.toAbsolutePath())error("Injected parent fsync failure")
  java.nio.channels.FileChannel.open(path,java.nio.file.StandardOpenOption.READ).use{it.force(true)}
 }else FileResumeJournal(baseDirectory,directory.resolve("resume"))
 if(scenario=="durability-fail"){check(runCatching{journal.inspect(binding,receipt)}.isFailure);check(!Files.exists(directory.resolve("resume"))||Files.walk(directory.resolve("resume")).use{it.noneMatch{p->p.fileName.toString().endsWith(".json")}});return}
 val checkpoint=journal.inspect(binding,receipt);check(checkpoint.frontierPage==0x18000&&checkpoint.commitPossible==false)
 val request="ef1faf4b-cd24-42c7-8508-8d51b4f10ad5"
 journal.acquire(binding,receipt,checkpoint.headSha256,request,77,"content://cloud/copy").use{s->
  s.append(ResumePhase.REVIEWED,null,checkpoint.frontierPage,false)
  s.append(ResumePhase.ERASE_INTENT,0,checkpoint.frontierPage,false)
  check(runCatching{journal.acquire(binding,receipt,checkpoint.headSha256,request,78,"content://cloud/copy")}.isFailure)
 }
 val after=journal.inspect(binding,receipt);check(after.frontierPage==0x18000&&after.sequence==2&&after.headSha256!=checkpoint.headSha256)
 when(scenario){
  "stale"->check(runCatching{journal.acquire(binding,receipt,checkpoint.headSha256,request,78,"content://cloud/copy")}.isFailure)
  "gap"->{Files.delete(directory.resolve("resume").resolve(binding.id).resolve("00000001.json"));check(runCatching{journal.inspect(binding,receipt)}.isFailure)}
  "corrupt"->{Files.write(directory.resolve("resume").resolve(binding.id).resolve("00000002.json"),"{}".toByteArray());check(runCatching{journal.inspect(binding,receipt)}.isFailure)}
  "base-changed"->{base.save(InstallJournalRecord(binding,4,InstallPhase.FAILED,0x18000,true,false,InstallPhase.PAGE_ERASE_INTENT,"changed"));check(runCatching{journal.inspect(binding,receipt)}.isFailure)}
  "frontier"->{journal.acquire(binding,receipt,after.headSha256,request,78,"content://cloud/copy").use{s->s.append(ResumePhase.REVIEWED,null,after.frontierPage,false);check(runCatching{s.append(ResumePhase.ERASE_INTENT,0,0,false)}.isFailure)}}
  "durability"->{val root=directory.resolve("resume").toAbsolutePath();val folder=root.resolve(binding.id)
   check(syncEvents.contains(directory.toAbsolutePath())&&syncEvents.contains(root)&&syncEvents.contains(folder))
   check(syncEvents.indexOf(directory.toAbsolutePath())<syncEvents.indexOf(folder))}
  "good"->{journal.acquire(binding,receipt,after.headSha256,request,78,"content://cloud/copy").use{s->s.append(ResumePhase.REVIEWED,null,after.frontierPage,false);s.append(ResumePhase.ERASE_INTENT,0x19000,0x19000,false)};check(journal.inspect(binding,receipt).frontierPage==0x19000)}
  else->error("Unknown scenario")
 }
}
