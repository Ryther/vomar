package org.openvimar.installer

import java.nio.file.Files
import java.nio.file.Path
import java.time.Instant
import org.openvimar.updater.DkBackupArchive
import org.openvimar.updater.DkBackupIdentity
import org.openvimar.updater.DkBackupPass
import org.openvimar.updater.DkBackupProvenance
import org.openvimar.updater.DkBackupRegion

internal fun produceBackup(directory:Path,output:Path) {
    val regions=DkBackupRegion.entries.associateWith{Files.readAllBytes(directory.resolve(it.fileName))}
    val ficr=regions.getValue(DkBackupRegion.FICR);val identity=DkBackupIdentity(word(ficr,0x60),word(ficr,0x64),word(ficr,0x100))
    fun pass()=DkBackupPass(identity,identity,regions.mapValues{it.value.copyOf()})
    val provenance=DkBackupProvenance("synthetic test","synthetic probe",3300,0x1366,0x1060,4,0x85,3,Instant.parse("2026-10-23T12:00:00Z"),Instant.parse("2026-10-23T12:02:00Z"))
    Files.write(output,DkBackupArchive.create(pass(),pass(),identity,provenance))
}

internal fun produceQuiescent(directory:Path,output:Path,method:String) {
    val first=listOf("flash.bin","ficr.bin","uicr.bin").associateWith{Files.readAllBytes(directory.resolve(it))}
    val second=first.mapValues{it.value.copyOf()}
    if(method=="mismatch")second.getValue("flash.bin")[100]=0
    val p=QuiescentProvenance("synthetic test","synthetic probe",3300,0x1366,0x1060,4,0x85,3)
    Files.write(output,QuiescentArchive.create(first,second,p,Instant.parse("2026-10-23T12:00:00Z"),Instant.parse("2026-10-23T12:02:00Z"),0,method=="reset-vector-catch",
        if(method=="paused-watchdog")ObservedWatchdogProfile(1,1,0x50000,1) else null))
}

internal fun failureSweep(args:Array<String>) {
    val directory=Path.of(args[4]);Files.createDirectories(directory)
    val base=directory.resolve("baseline");Files.createDirectory(base)
    engineProbe(arrayOf("install",args[1],args[2],args[3],"good",base.toString()))
    val trace=Files.readAllLines(base.resolve("trace.txt"))
    val selected=trace.indices.filter{trace[it].startsWith("erase:")||trace[it].startsWith("program:")||trace[it].startsWith("journal:")||trace[it] in setOf("begin-journal","load-journal","acquire","close")}.toMutableSet()
    for(prefix in listOf("ficr","identity","uicr","read:0:","read:1044480:")){
        val matches=trace.indices.filter{trace[it].startsWith(prefix)};if(matches.isNotEmpty()){selected+=matches.first();selected+=matches.last()}
    }
    for(index in selected.sorted()){
        val path=directory.resolve("failure-${index+1}");Files.createDirectory(path)
        engineProbe(arrayOf("install",args[1],args[2],args[3],"fail-${index+1}",path.toString()))
        val failed=Files.readAllLines(path.resolve("trace.txt"))
        check(failed.size>index&&failed[index]==trace[index])
        check(failed.drop(index+1).none{it.startsWith("erase:")||it.startsWith("program:")}){"Mutation after failed IO/intent boundary"}
        // Keep auditable failure context without hundreds of duplicate1MiB
        // synthetic images/whole-session traces in the temporary test output.
        Files.write(path.resolve("trace.txt"),failed.drop(maxOf(0,index-2)))
        for(name in listOf("export.zip","anchor.bin","table.bin"))Files.delete(path.resolve(name))
    }
    Files.writeString(directory.resolve("count.txt"),selected.size.toString())
}
