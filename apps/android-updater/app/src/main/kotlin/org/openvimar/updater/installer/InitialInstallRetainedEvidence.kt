package org.openvimar.updater.installer

import org.openvimar.installer.*
import org.openvimar.installer.resume.*
import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.Path
import java.nio.file.StandardOpenOption
import java.nio.file.StandardCopyOption
import java.util.UUID

internal class RetainedInitialInstall(val binding:InstallBinding,val initialReceipt:OriginalExportReceipt,
    private val original:VerifiedOriginal?,val checkpoint:ResumeCheckpoint,val startUncertain:Boolean){
    val originalAvailable get()=original!=null
    fun reopenOriginal(document:String,read:(String)->ByteArray)=ResumeOriginal.reopen(requireNotNull(original){"Protected original is missing; automatic recovery is blocked"},initialReceipt,document,read)
    fun option()=InitialInstallResumeOption(binding.id,binding.releaseSha256,binding.archiveSha256,initialReceipt.document,originalAvailable,
        checkpoint.headSha256,checkpoint.frontierPage,checkpoint.commitPossible,
        if(startUncertain)"Start acknowledgement uncertain; repair may reset custom settings"
        else "Interrupted or verified-unstarted installation; repair may reset custom settings")
}

/** Private evidence, never persisted approval. Initial export receipt is
 * immutable; completed starts suppress ordinary interrupted-install offers. */
internal class InitialInstallRetainedEvidence(private val root:Path,private val original:(String)->VerifiedOriginal?,
    private val forceDirectory:(Path)->Unit=DurableInstallFiles::syncDirectory){
    private val base=root.resolve("transactions");private val exports=root.resolve("exports");private val starts=root.resolve("starts")
    val journal=FileResumeJournal(base,root.resolve("resume"))
    private fun id(value:String){require(Regex("[0-9a-f]{64}").matches(value))}
    private fun read(path:Path,limit:Int=32768):ByteArray{
        require(Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)&&Files.size(path) in 1..limit.toLong()){"Private recovery evidence is missing or invalid"}
        return Files.newInputStream(path).use{input->val out=java.io.ByteArrayOutputStream();val buffer=ByteArray(2048)
            while(true){val n=input.read(buffer);if(n<0)break;require(n>0&&out.size()+n<=limit);out.write(buffer,0,n)};out.toByteArray()}
    }
    private fun write(channel:FileChannel,bytes:ByteArray){val b=ByteBuffer.wrap(bytes);while(b.hasRemaining())channel.write(b);channel.force(true)}
    @Synchronized fun saveExport(material:OriginalMaterial,binding:InstallBinding){
        val receipt=OriginalExportReceipt.fromVerifiedExport(material,binding);DurableInstallFiles.ensureDirectory(exports)
        val path=exports.resolve("${binding.id}.json");val bytes=receipt.encode()
        if(Files.exists(path,LinkOption.NOFOLLOW_LINKS))require(read(path).contentEquals(bytes)){"Initial export receipt cannot be changed or replaced"}
        else FileChannel.open(path,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE).use{write(it,bytes)}
        // Also mandatory for existing-exact retries after a failed prior sync.
        forceDirectory(exports);require(OriginalExportReceipt.parse(read(path)).encode().contentEquals(bytes))
    }
    private data class Start(val sequence:Int,val request:String,val acknowledged:Boolean)
    private fun encodeStart(binding:InstallBinding,start:Start)=("{\"bindingId\":\"${binding.id}\",\"phase\":\"${if(start.acknowledged)"ACKNOWLEDGED" else "INTENT"}\",\"requestId\":\"${start.request}\",\"schemaVersion\":1,\"sequence\":${start.sequence}}\n").toByteArray()
    private fun loadStart(binding:InstallBinding):Start?{
        val path=starts.resolve("${binding.id}.json");if(!Files.exists(path,LinkOption.NOFOLLOW_LINKS))return null
        // Exact canonical fixed record, no coercing JSONObject parser.
        val text=String(read(path),Charsets.UTF_8)
        val match=requireNotNull(Regex("\\{\"bindingId\":\"([0-9a-f]{64})\",\"phase\":\"(INTENT|ACKNOWLEDGED)\",\"requestId\":\"([0-9a-f-]{36})\",\"schemaVersion\":1,\"sequence\":([1-9][0-9]{0,9})}\\n").matchEntire(text)){"Invalid private start evidence"}
        require(match.groupValues[1]==binding.id)
        val value=Start(match.groupValues[4].toInt(),match.groupValues[3],match.groupValues[2]=="ACKNOWLEDGED")
        require(UUID.fromString(value.request).toString()==value.request&&encodeStart(binding,value).contentEquals(text.toByteArray()));return value
    }
    @Synchronized fun recordStart(binding:InstallBinding,requestId:String,acknowledged:Boolean){
        require(UUID.fromString(requestId).toString()==requestId);val receipt=OriginalExportReceipt.parse(read(exports.resolve("${binding.id}.json")))
        require(receipt.bindingId==binding.id&&receipt.archiveSha256==binding.archiveSha256)
        val prior=loadStart(binding);if(acknowledged)require(prior!=null&&!prior.acknowledged&&prior.request==requestId){"Start acknowledgement has no matching durable intent"}
        val next=Start(Math.addExact(prior?.sequence?:0,1),requestId,acknowledged);val bytes=encodeStart(binding,next)
        DurableInstallFiles.ensureDirectory(starts);val temporary=starts.resolve("${binding.id}-${UUID.randomUUID()}.tmp")
        try{
            FileChannel.open(temporary,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE).use{write(it,bytes)}
            Files.move(temporary,starts.resolve("${binding.id}.json"),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING)
            forceDirectory(starts);require(loadStart(binding)==next)
        }finally{Files.deleteIfExists(temporary)}
    }
    @Synchronized fun reopen(bindingId:String):RetainedInitialInstall{
        id(bindingId);val record=requireNotNull(FileInstallJournal(base).load(bindingId)){"Initial journal is missing"};val binding=record.binding
        val receipt=OriginalExportReceipt.parse(read(exports.resolve("$bindingId.json")))
        require(receipt.bindingId==bindingId&&receipt.archiveSha256==binding.archiveSha256)
        val stored=original(binding.archiveSha256)
        if(stored!=null)require(stored.archiveSha256==binding.archiveSha256&&stored.identity==binding.target){"Private original differs from retained journal"}
        val head=journal.inspect(binding,receipt);val start=loadStart(binding)
        return RetainedInitialInstall(binding,receipt,stored,head,start!=null&&!start.acknowledged)
    }
    @Synchronized fun options(target:TargetIdentity):List<InitialInstallResumeOption>{
        if(!Files.exists(base,LinkOption.NOFOLLOW_LINKS))return emptyList()
        require(Files.isDirectory(base,LinkOption.NOFOLLOW_LINKS));val records=mutableListOf<InstallJournalRecord>();var count=0
        Files.newDirectoryStream(base).use{entries->for(path in entries){
            require(++count<=1024){"Too many private installation records; explicit review required"};val name=path.fileName.toString()
            if(Regex("[0-9a-f]{64}-[0-9a-f-]{36}\\.tmp").matches(name))continue
            require(Regex("[0-9a-f]{64}\\.json").matches(name)){"Unknown private installation evidence"}
            val record=requireNotNull(FileInstallJournal(base).load(name.removeSuffix(".json")))
            if(record.binding.target.uid0==target.uid0&&record.binding.target.uid1==target.uid1){require(record.binding.target==target){"Retained UID geometry differs from live target"};records.add(record)}
        }}
        val retained=records.map{reopen(it.binding.id)}
        // The original base is immutable: a PREPARED base can acquire actual
        // write uncertainty later in its separately linked resume journal.
        val progressed=retained.filter{it.checkpoint.frontierPage>=0||it.checkpoint.commitPossible}
        val selected=if(progressed.isNotEmpty())progressed else retained
        require(selected.size<=1){"Multiple retained installations match this UID; automatic selection is blocked"}
        return selected.mapNotNull{if(loadStart(it.binding)?.acknowledged==true)null else it.option()}
    }
}
