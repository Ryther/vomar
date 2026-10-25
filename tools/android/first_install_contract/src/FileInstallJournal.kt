package org.openvimar.installer

import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.nio.file.FileAlreadyExistsException
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import java.nio.file.StandardOpenOption
import java.util.UUID

/** Caller supplies an app-private dedicated directory, not an export/input
 * folder. Linux/JVM-tested durable adapter; Android SAF integration is separate.
 * An incomplete first record still reserves the binding and fails closed. */
class FileInstallJournal(private val directory:Path):InstallJournalStore {
    private fun path(id:String):Path {require(Regex("[0-9a-f]{64}").matches(id));return directory.resolve("$id.json")}
    @Synchronized override fun load(bindingId:String):InstallJournalRecord? {
        val file=path(bindingId);if(!Files.exists(file,LinkOption.NOFOLLOW_LINKS))return null
        require(Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS)&&Files.size(file) in 1..16384)
        val bytes=Files.newInputStream(file).use{input->val out=java.io.ByteArrayOutputStream();val b=ByteArray(1024)
            while(true){val n=input.read(b);if(n<0)break;require(out.size()+n<=16384);out.write(b,0,n)};out.toByteArray()}
        return decode(bytes).also{require(it.binding.id==bindingId)}
    }
    @Synchronized override fun begin(record:InstallJournalRecord):Boolean {
        require(record.sequence==1&&record.phase==InstallPhase.PREPARED&&record.address==null&&!record.mutationMayHaveStarted&&!record.commitMayHaveBeenWritten)
        val bytes=encode(record);DurableInstallFiles.ensureDirectory(directory)
        try {
            FileChannel.open(path(record.binding.id),StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE).use{channel->write(channel,bytes)}
        } catch(_:FileAlreadyExistsException){return false}
        syncDirectory();return true
    }
    @Synchronized override fun save(record:InstallJournalRecord) {
        val bytes=encode(record);val prior=requireNotNull(load(record.binding.id)){"Journal must be atomically reserved before updating"}
        require(prior.binding==record.binding&&record.sequence==prior.sequence+1){"Stale or foreign transaction intent"}
        require(!prior.mutationMayHaveStarted||record.mutationMayHaveStarted)
        require(!prior.commitMayHaveBeenWritten||record.commitMayHaveBeenWritten)
        val temp=directory.resolve("${record.binding.id}-${UUID.randomUUID()}.tmp");var created=false
        try {
            FileChannel.open(temp,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE).use{channel->created=true;write(channel,bytes)}
            Files.move(temp,path(record.binding.id),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING)
            syncDirectory()
        } finally {if(created)Files.deleteIfExists(temp)}
    }
    private fun write(channel:FileChannel,bytes:ByteArray){val buffer=ByteBuffer.wrap(bytes);while(buffer.hasRemaining())channel.write(buffer);channel.force(true)}
    private fun syncDirectory()=DurableInstallFiles.syncDirectory(directory)
    private fun binding(value:InstallBinding):Map<String,Any?> {
        val t=value.target
        return mapOf("id" to value.id,"target" to mapOf("uid0" to t.uid0,"uid1" to t.uid1,"variant" to t.variant,"part" to t.part,
            "flashSize" to t.flashSize.toLong(),"pageSize" to t.pageSize.toLong(),"ramSize" to t.ramSize.toLong(),"uicrSize" to t.uicrSize.toLong()),
            "archiveSha256" to value.archiveSha256,"releaseSha256" to value.releaseSha256,"familySha256" to value.familySha256,
            "anchorSha256" to value.anchorSha256,"tableSha256" to value.tableSha256,"bodySha256" to value.bodySha256,"installedSha256" to value.installedSha256)
    }
    private fun encode(record:InstallJournalRecord):ByteArray {
        val map=mapOf("schemaVersion" to 1L,"binding" to binding(record.binding),"sequence" to record.sequence.toLong(),"phase" to record.phase.name,
            "address" to record.address?.toLong(),"mutationMayHaveStarted" to record.mutationMayHaveStarted,"commitMayHaveBeenWritten" to record.commitMayHaveBeenWritten,
            "failurePhase" to record.failurePhase?.name,"message" to record.message)
        return (StrictJson.canonical(map)+"\n").toByteArray().also{require(it.size<=16384);require(decode(it)==record)}
    }
    private fun decode(bytes:ByteArray):InstallJournalRecord {
        val m=keys(StrictJson.parse(bytes),setOf("schemaVersion","binding","sequence","phase","address","mutationMayHaveStarted","commitMayHaveBeenWritten","failurePhase","message"))
        require(m["schemaVersion"]==1L)
        val b=keys(m["binding"],setOf("id","target","archiveSha256","releaseSha256","familySha256","anchorSha256","tableSha256","bodySha256","installedSha256"))
        val t=keys(b["target"],setOf("uid0","uid1","variant","part","flashSize","pageSize","ramSize","uicrSize"))
        fun number(v:Any?,max:Long):Long {require(v is Long&&v in 0..max);return v}
        val target=TargetIdentity(number(t["uid0"],0xffffffffL),number(t["uid1"],0xffffffffL),number(t["variant"],0xfffffffeL))
        require(target.variant>0&&t["part"]==target.part&&t["flashSize"]==target.flashSize.toLong()&&t["pageSize"]==target.pageSize.toLong()&&t["ramSize"]==target.ramSize.toLong()&&t["uicrSize"]==target.uicrSize.toLong())
        fun hash(name:String):String {val v=b[name];require(v is String&&Regex("[0-9a-f]{64}").matches(v));return v}
        val binding=InstallBinding(target,hash("archiveSha256"),hash("releaseSha256"),hash("familySha256"),hash("anchorSha256"),hash("tableSha256"),hash("bodySha256"),hash("installedSha256"))
        require(b["id"]==binding.id)
        val sequence=number(m["sequence"],Int.MAX_VALUE.toLong()).toInt();require(sequence>0)
        val phase=InstallPhase.valueOf(m["phase"] as String)
        val address=m["address"]?.let{number(it,0xffffc).toInt().also{n->require(n%4==0)}}
        val mutated=m["mutationMayHaveStarted"] as Boolean;val commit=m["commitMayHaveBeenWritten"] as Boolean
        require(!commit||mutated)
        val failure=m["failurePhase"]?.let{InstallPhase.valueOf(it as String)};require((phase==InstallPhase.FAILED)==(failure!=null))
        val message=m["message"] as String;require(message.length<=1024)
        if(phase==InstallPhase.PAGE_ERASE_INTENT)require(address!=null&&address%4096==0&&mutated&&!commit)
        if(phase==InstallPhase.PAGE_WRITE_INTENT)require(address!=null&&mutated&&!commit)
        if(phase in setOf(InstallPhase.COMMIT_INTENT,InstallPhase.COMMIT_WRITTEN))require(address==0xb0fc&&commit)
        if(phase==InstallPhase.VERIFIED)require(address==null&&mutated&&commit)
        return InstallJournalRecord(binding,sequence,phase,address,mutated,commit,failure,message)
    }
}
