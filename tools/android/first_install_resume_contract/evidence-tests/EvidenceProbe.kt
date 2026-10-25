package org.openvimar.updater.installer

import org.openvimar.installer.*
import org.openvimar.installer.resume.*
import java.nio.file.Files
import java.nio.file.Path
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec

fun main(args:Array<String>){
 val directory=Path.of(args[4]);val scenario=args[5];val original=OriginalArchive.verify(Files.readAllBytes(Path.of(args[1])))
 val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(Files.readAllBytes(Path.of(args[3]))));val candidate=CandidateRelease.inspect(Files.readAllBytes(Path.of(args[2])),key,"9.0.0")
 var bytes=byteArrayOf();val material=OriginalArchive.exportAndReopen(original,object:ArchiveExport{override fun create(raw:ByteArray):String{bytes=raw;return "content://initial/original"};override fun reopen(document:String)=bytes}).deriveOriginal()
 val request="ef1faf4b-cd24-42c7-8508-8d51b4f10ad5";val plan=candidate.preparePlan(material,candidate.reviewOneBench(material.identity,request,77,candidate.releaseSha256),request,77)
 val base=FileInstallJournal(directory.resolve("transactions"));check(base.begin(InstallJournalRecord(plan.binding,1,InstallPhase.PREPARED,null,false,false)));if(scenario!="prefer-resumed")base.save(InstallJournalRecord(plan.binding,2,InstallPhase.PAGE_ERASE_INTENT,0,true,false))
 var originalAvailable=true;var syncs=0;var failSync=false
 val evidence=InitialInstallRetainedEvidence(directory,{if(originalAvailable)original else null}){path->syncs++;DurableInstallFiles.syncDirectory(path);if(failSync)error("Injected directory sync failure")}
 if(scenario!="missing-receipt")evidence.saveExport(material,plan.binding)
 if(scenario=="missing-receipt"){check(runCatching{evidence.options(material.identity)}.isFailure);return}
 if(scenario=="corrupt-receipt"){Files.write(directory.resolve("exports/${plan.binding.id}.json"),"{}".toByteArray());check(runCatching{evidence.options(material.identity)}.isFailure);return}
 if(scenario=="missing-original")originalAvailable=false
 if(scenario=="retry-sync"){
  failSync=true;check(runCatching{evidence.saveExport(material,plan.binding)}.isFailure);failSync=false;val previous=syncs;evidence.saveExport(material,plan.binding);check(syncs>previous)
 }
 if(scenario=="prefer-resumed"){
  val receipt=OriginalExportReceipt.fromVerifiedExport(material,plan.binding);val head=evidence.journal.inspect(plan.binding,receipt)
  evidence.journal.acquire(plan.binding,receipt,head.headSha256,request,77,"content://cloud/copy").use{s->s.append(ResumePhase.REVIEWED,null,-1,false);s.append(ResumePhase.ERASE_INTENT,0,0,false)}
  val other=plan.binding.copy(releaseSha256="00".repeat(32));check(base.begin(InstallJournalRecord(other,1,InstallPhase.PREPARED,null,false,false)));evidence.saveExport(material,other)
 }
 val options=evidence.options(material.identity);check(options.size==1&&options.single().bindingId==plan.binding.id&&options.single().originalAvailable==originalAvailable)
 if(scenario=="wrong-target"){check(evidence.options(material.identity.copy(uid0=123)).isEmpty());return}
 val record=evidence.reopen(plan.binding.id)
 if(scenario=="missing-original"){check(runCatching{record.reopenOriginal("content://cloud/copy"){bytes}}.isFailure);return}
 check(record.reopenOriginal("content://cloud/copy"){bytes}.archiveSha256==original.archiveSha256)
 if(scenario=="start"){
  evidence.recordStart(plan.binding,request,false);check(evidence.options(material.identity).single().classification.contains("uncertain"))
  evidence.recordStart(plan.binding,request,true);check(evidence.options(material.identity).isEmpty())
 }
 if(scenario=="multiple"){
  val b=plan.binding.copy(releaseSha256="00".repeat(32));check(base.begin(InstallJournalRecord(b,1,InstallPhase.PREPARED,null,false,false)));base.save(InstallJournalRecord(b,2,InstallPhase.PAGE_ERASE_INTENT,0,true,false));check(runCatching{evidence.options(material.identity)}.isFailure)
 }
}
