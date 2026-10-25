package org.openvimar.installer.resume

import org.openvimar.installer.*
import java.nio.file.Files
import java.nio.file.Path
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec

fun main(args:Array<String>){
 if(args[0]=="engine"){resumeEngineProbe(args);return}
 if(args[0]=="journal"){journalProbe(Path.of(args[1]),args[2]);return}
 val bytes=Files.readAllBytes(Path.of(args[1]));val original=OriginalArchive.verify(bytes)
 val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(Files.readAllBytes(Path.of(args[3]))))
 val candidate=CandidateRelease.inspect(Files.readAllBytes(Path.of(args[2])),key,"9.0.0")
 var exported=byteArrayOf();val initialUri="content://original/document/one"
 val material=OriginalArchive.exportAndReopen(original,object:ArchiveExport{
  override fun create(bytes:ByteArray):String{exported=bytes.copyOf();return initialUri}
  override fun reopen(document:String)=exported.copyOf()
 }).deriveOriginal()
 val request="ef1faf4b-cd24-42c7-8508-8d51b4f10ad5"
 val plan=candidate.preparePlan(material,candidate.reviewOneBench(material.identity,request,77,candidate.releaseSha256),request,77)
 var binding=plan.binding
 if(args[5]=="wrong-binding")binding=binding.copy(archiveSha256="00".repeat(32))
 val receipt=OriginalExportReceipt.fromVerifiedExport(material,binding)
 val parsed=OriginalExportReceipt.parse(receipt.encode());check(parsed.sha256==receipt.sha256)
 val selected=if(args[5]=="moved")"content://cloud/document/moved-original" else initialUri
 val reopened=ResumeOriginal.reopen(original,parsed,selected){uri->check(uri==selected);bytes.copyOf().also{if(args[5]=="changed-backup")it[100]=(it[100].toInt() xor 1).toByte()}}
 check(reopened.identity==original.identity&&reopened.archiveSha256==original.archiveSha256&&reopened.selectedDocument==selected)
 check(reopened.initialReceipt.sha256==receipt.sha256&&receipt.document==initialUri)
 Files.write(Path.of(args[4],"receipt.json"),receipt.encode())
 Files.writeString(Path.of(args[4],"selected.txt"),reopened.selectedDocument)
}
