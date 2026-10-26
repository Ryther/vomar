package org.openvimar.installer

import java.nio.file.Files
import java.nio.file.Path
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec

fun main(args:Array<String>) {
    when(args[0]) {
        "original-restore" -> originalRestoreProbe(args)
        "local-inspect" -> {
            val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(Files.readAllBytes(Path.of(args[2]))))
            val raw=Files.readAllBytes(Path.of(args[1]))
            val local=CandidateRelease.inspectLocal(raw,key,"9.0.0")
            check(local.releaseSha256==sha256(raw))
            if(args.getOrNull(3)=="no-handoff")check(local.watchdogHandoff==null)
            val ble=org.openvimar.updater.core.BleTrialCandidate.inspectLocal(raw,key,"9.0.0")
            check(ble.digest==local.releaseSha256)
        }
        "durable-directories" -> durableDirectoriesProbe(Path.of(args[1]))
        "watchdog-authority" -> {
            val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(Files.readAllBytes(Path.of(args[2]))))
            val bytes=Files.readAllBytes(Path.of(args[1]));val target=TargetIdentity(0x11223344,0x55667788,0x41414430)
            val grant=if(args[3]=="candidate")CandidateRelease.inspect(bytes,key,"9.0.0").authorizeWatchdogHandoff(target,77)
                else CommonRelease.verify(bytes,key,"9.0.0").authorizeWatchdogHandoff(target,77)
            val checked=checkNotNull(grant);checked.requireTarget(target,77)
            check(runCatching{checked.requireTarget(target.copy(uid0=target.uid0 xor 1),77)}.isFailure)
            check(runCatching{checked.requireTarget(target,78)}.isFailure)
            check(checked.policy=="paused-reset-before-main-v1")
            val binding=InstallBinding(target,"11".repeat(32),checked.releaseSha256,checked.familySha256,"22".repeat(32),"33".repeat(32),"44".repeat(32),"55".repeat(32))
            checked.requireBinding(binding,77)
            check(runCatching{checked.requireBinding(binding.copy(releaseSha256="00".repeat(32)),77)}.isFailure)
            check(runCatching{checked.requireBinding(binding.copy(familySha256="00".repeat(32)),77)}.isFailure)
        }
        "candidate-inspect" -> {
            val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(Files.readAllBytes(Path.of(args[2]))))
            val candidate=CandidateRelease.inspect(Files.readAllBytes(Path.of(args[1])),key,"9.0.0")
            val report=candidate.qualification();Files.write(Path.of(args[3]),report);report.fill(0)
            check(candidate.qualification().any{it!=0.toByte()})
        }
        "candidate-permit" -> {
            val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(Files.readAllBytes(Path.of(args[2]))))
            val candidate=CandidateRelease.inspect(Files.readAllBytes(Path.of(args[1])),key,"9.0.0")
            val original=OriginalArchive.verify(Files.readAllBytes(Path.of(args[3])))
            var exported=byteArrayOf()
            val material=OriginalArchive.exportAndReopen(original,object:ArchiveExport{override fun create(bytes:ByteArray):String{exported=bytes;return "synthetic-export"};override fun reopen(document:String)=exported}).deriveOriginal()
            val request="ef1faf4b-cd24-42c7-8508-8d51b4f10ad5"
            check(runCatching{candidate.reviewOneBench(material.identity,request,77,"00".repeat(32))}.isFailure)
            val permit=candidate.reviewOneBench(material.identity,request,77,candidate.releaseSha256)
            check(runCatching{candidate.preparePlan(material,permit,request,78)}.isFailure)
            check(runCatching{candidate.preparePlan(material,permit,"00000000-0000-0000-0000-000000000000",77)}.isFailure)
            val preview=candidate.previewBinding(material)
            val plan=candidate.preparePlan(material,permit,request,77);check(plan.binding.target==material.identity&&plan.binding==preview)
            check(runCatching{candidate.preparePlan(material,permit,request,77)}.isFailure)
            val revoked=candidate.reviewOneBench(material.identity,request,77,candidate.releaseSha256);revoked.close()
            check(runCatching{candidate.preparePlan(material,revoked,request,77)}.isFailure)
        }
        "install" -> engineProbe(args)
        "journal" -> journalProbe(Path.of(args[1]))
        "produce-backup" -> produceBackup(Path.of(args[1]),Path.of(args[2]))
        "produce-quiescent" -> produceQuiescent(Path.of(args[1]),Path.of(args[2]),args[3])
        "sweep" -> failureSweep(args)
        "anchor" -> {
            val page=AnchorV1.encode(args[2].toLong(16),args[3].toLong(16),args[4].toLong(16),
                args[5],args[6],args[7])
            Files.write(Path.of(args[1]),page)
        }
        "backup" -> {
            val raw=Files.readAllBytes(Path.of(args[1]))
            val original=OriginalArchive.verify(raw)
            val saved=raw.copyOf();raw.fill(0) // Caller mutation cannot alter verified source bytes.
            val exported=OriginalArchive.exportAndReopen(original,object:ArchiveExport {
                override fun create(bytes:ByteArray):String? {
                    check(bytes.contentEquals(saved))
                    if(args[4]=="cancel")return null
                    if(args[4]=="export-fails")error("Export failed")
                    Files.write(Path.of(args[2]),bytes);return args[2]
                }
                override fun reopen(document:String):ByteArray {
                    if(args[4]=="reopen-fails")error("Reopen failed")
                    return Files.readAllBytes(Path.of(document)).also{
                        if(args[4]=="changed")it[10]=(it[10].toInt() xor 1).toByte()
                    }.let{if(args[4]=="same-regions-different-zip")it+byteArrayOf(0) else it}
                }
            })
            val material=exported.deriveOriginal()
            Files.write(Path.of(args[3],"anchor.bin"),material.anchor())
            Files.write(Path.of(args[3],"table.bin"),material.table())
        }
        "release" -> {
            val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(Files.readAllBytes(Path.of(args[2]))))
            val release=CommonRelease.verify(Files.readAllBytes(Path.of(args[1])),key,args.getOrNull(4)?:"0.5.0")
            if(args.getOrNull(5)=="public-components") {
                val directory=Path.of(args[3]);Files.createDirectories(directory)
                Files.write(directory.resolve("loader.bin"),release.loader())
                Files.write(directory.resolve("main.signed.bin"),release.main())
                Files.write(directory.resolve("recovery.signed.bin"),release.recovery())
                val descriptor=release.descriptor();Files.write(directory.resolve("first-install.json"),descriptor)
                descriptor.fill(0);check(release.descriptor().any{it!=0.toByte()})
                return
            }
            Files.writeString(Path.of(args[3]),release.familySha256+"\n")
        }
        else -> error("Unknown test probe command")
    }
}
