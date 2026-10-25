package org.openvimar.installer.resume

import org.openvimar.installer.*
import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.nio.channels.FileLock
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import java.nio.file.StandardOpenOption
import java.util.UUID

/** Separate from the immutable first-attempt journal. Each intent extends a
 * hash chain bound to its exact original journal and initial export receipt. */
enum class ResumePhase {REVIEWED,VALIDATING,ERASE_INTENT,WRITE_INTENT,BODY_VERIFIED,COMPLETE_IMAGE_VERIFIED,COMMIT_INTENT,FINAL_VERIFY,VERIFIED,FAILED}
data class ResumeCheckpoint(val baseSha256:String,val headSha256:String,val sequence:Int,val frontierPage:Int,val commitPossible:Boolean)
class FileResumeJournal internal constructor(private val baseDirectory:Path,private val directory:Path,
    private val forceDirectory:(Path)->Unit) {
    constructor(baseDirectory:Path,directory:Path):this(baseDirectory,directory,{path->FileChannel.open(path,StandardOpenOption.READ).use{it.force(true)}})
    companion object {private const val MAX_RECORDS=100000;private const val LAST=0xff000}
    private fun id(value:String){require(Regex("[0-9a-f]{64}").matches(value))}
    private fun bounded(path:Path,maximum:Int):ByteArray {
        require(Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)&&Files.size(path) in 1..maximum.toLong()){"Unreadable recovery evidence"}
        return Files.newInputStream(path).use{input->val out=java.io.ByteArrayOutputStream();val buffer=ByteArray(2048)
            while(true){val count=input.read(buffer);if(count<0)break;require(count>0&&out.size()+count<=maximum);out.write(buffer,0,count)};out.toByteArray()}
    }
    private data class Base(val record:InstallJournalRecord,val digest:String)
    private fun base(binding:InstallBinding):Base {
        id(binding.id);val path=baseDirectory.resolve("${binding.id}.json");val before=bounded(path,16384)
        val record=requireNotNull(FileInstallJournal(baseDirectory).load(binding.id)){"Initial transaction evidence is missing"}
        require(record.binding==binding&&before.contentEquals(bounded(path,16384))){"Initial journal changed during review"}
        return Base(record,sha256(before))
    }
    private fun frontier(record:InstallJournalRecord):Int {
        if(!record.mutationMayHaveStarted)return -1
        if(record.commitMayHaveBeenWritten)return LAST
        return when(record.failurePhase?:record.phase){
            InstallPhase.PAGE_ERASE_INTENT,InstallPhase.PAGE_WRITE_INTENT->requireNotNull(record.address) and 4095.inv()
            InstallPhase.BODY_VERIFY,InstallPhase.BODY_VERIFIED,InstallPhase.COMMIT_INTENT,InstallPhase.COMMIT_WRITTEN,InstallPhase.FINAL_VERIFY,InstallPhase.VERIFIED->LAST
            else->error("Initial journal cannot establish an issued-page frontier")
        }
    }
    private fun seed(binding:InstallBinding,receipt:OriginalExportReceipt,base:Base)=ResumeCheckpoint(base.digest,
        sha256(("VIMAR30805-EXPLICIT-RESUME-V1\n${binding.id}\n${base.digest}\n${receipt.sha256}\n").toByteArray()),0,frontier(base.record),base.record.commitMayHaveBeenWritten)
    private fun durableDirectory(path:Path)=DurableInstallFiles.ensureDirectory(path,forceDirectory)
    private fun lock(binding:InstallBinding):Triple<Path,FileChannel,FileLock> {
        id(binding.id);durableDirectory(directory)
        val folder=directory.resolve(binding.id);durableDirectory(folder)
        val lockPath=folder.resolve(".lock");require(!Files.isSymbolicLink(lockPath))
        val channel=FileChannel.open(lockPath,StandardOpenOption.CREATE,StandardOpenOption.WRITE)
        try{return Triple(folder,channel,requireNotNull(channel.tryLock()){"Another explicit resume owns this journal"})}
        catch(error:Exception){channel.close();throw error}
    }
    private fun checked(binding:InstallBinding,receipt:OriginalExportReceipt,folder:Path):ResumeCheckpoint {
        require(receipt.bindingId==binding.id&&receipt.archiveSha256==binding.archiveSha256){"Initial export receipt does not match reviewed binding"}
        val initial=base(binding);var checkpoint=seed(binding,receipt,initial);val paths=mutableListOf<Path>();var count=0
        Files.newDirectoryStream(folder).use{entries->for(path in entries){
            require(++count<=MAX_RECORDS+1024){"Too much recovery evidence"};val name=path.fileName.toString()
            if(name==".lock")continue
            if(Regex("[0-9a-f-]{36}\\.tmp").matches(name))continue // Incomplete publication is never authority.
            require(Regex("[0-9]{8}\\.json").matches(name)){"Unknown recovery evidence"};paths.add(path)
        }}
        paths.sortBy{it.fileName.toString()};require(paths.size<=MAX_RECORDS)
        var priorRequest:String?=null;var priorGeneration=0L
        for((index,path) in paths.withIndex()){
            require(path.fileName.toString()=="%08d.json".format(index+1)){"Missing recovery journal record"}
            val bytes=bounded(path,32768);val m=keys(StrictJson.parse(bytes),setOf("schemaVersion","bindingId","baseSha256","exportReceiptSha256","previousSha256","sequence","requestId","generation","selectedDocument","phase","address","frontierPage","commitPossible","message"))
            require(m["schemaVersion"]==1L&&m["bindingId"]==binding.id&&m["baseSha256"]==initial.digest&&m["exportReceiptSha256"]==receipt.sha256&&m["previousSha256"]==checkpoint.headSha256&&m["sequence"]==(index+1).toLong()){"Foreign or broken recovery chain"}
            val request=m["requestId"] as String;require(UUID.fromString(request).toString()==request)
            val generation=m["generation"] as Long;require(generation>0)
            val selected=m["selectedDocument"] as String;require(selected.isNotBlank()&&selected.length<=4096)
            val phase=ResumePhase.valueOf(m["phase"] as String)
            require((request==priorRequest&&generation==priorGeneration)||phase==ResumePhase.REVIEWED){"A new recovery attempt requires fresh review"}
            val address=m["address"]?.let{require(it is Long&&it in 0..0xffffc&&it%4==0L);it.toInt()}
            val high=m["frontierPage"] as Long;require(high in -1..LAST.toLong());val commit=m["commitPossible"] as Boolean
            validate(checkpoint,phase,address,high.toInt(),commit)
            require(m["message"] is String&&(m["message"] as String).length<=1024)
            require((StrictJson.canonical(m)+"\n").toByteArray().contentEquals(bytes)){"Noncanonical recovery journal"}
            checkpoint=ResumeCheckpoint(initial.digest,sha256(bytes),index+1,high.toInt(),commit);priorRequest=request;priorGeneration=generation
        }
        require(base(binding).digest==initial.digest){"Initial journal changed during recovery review"};return checkpoint
    }
    private fun validate(prior:ResumeCheckpoint,phase:ResumePhase,address:Int?,frontier:Int,commit:Boolean){
        require(frontier==-1||frontier in 0..LAST&&frontier%4096==0)
        require(frontier>=prior.frontierPage&&(!prior.commitPossible||commit)){"Recovery uncertainty cannot shrink"}
        if(frontier>prior.frontierPage)require(phase==ResumePhase.ERASE_INTENT&&address==frontier&&frontier==(if(prior.frontierPage==-1)0 else prior.frontierPage+4096)){"Only the next issued-page intent advances the frontier"}
        // A complete desired body may match still-original tail pages. Commit
        // does not authorize repairing those NEVER-issued pages on a later try.
        if(commit&&!prior.commitPossible)require(phase in setOf(ResumePhase.COMMIT_INTENT,ResumePhase.COMPLETE_IMAGE_VERIFIED)&&frontier>=0xb000)
        when(phase){
            ResumePhase.ERASE_INTENT->require(address!=null&&address%4096==0&&address<=frontier)
            ResumePhase.WRITE_INTENT->require(address!=null&&(address and 4095.inv())<=frontier)
            ResumePhase.COMMIT_INTENT->require(address==0xb0fc&&commit&&frontier>=0xb000)
            else->require(address==null)
        }
        if(phase==ResumePhase.VERIFIED)require(commit&&frontier>=0xb000)
    }
    fun inspect(binding:InstallBinding,receipt:OriginalExportReceipt):ResumeCheckpoint {
        val (folder,channel,held)=lock(binding)
        try{return checked(binding,receipt,folder)}finally{held.release();channel.close()}
    }
    fun acquire(binding:InstallBinding,receipt:OriginalExportReceipt,expectedHead:String,requestId:String,generation:Long,selectedDocument:String):Session {
        require(UUID.fromString(requestId).toString()==requestId&&generation>0&&selectedDocument.isNotBlank()&&selectedDocument.length<=4096)
        val (folder,channel,held)=lock(binding)
        try{val checkpoint=checked(binding,receipt,folder);require(checkpoint.headSha256==expectedHead){"Recovery journal changed; explicit review must be repeated"}
            return Session(binding,receipt,folder,channel,held,checkpoint,requestId,generation,selectedDocument)}
        catch(error:Exception){held.release();channel.close();throw error}
    }
    inner class Session internal constructor(private val binding:InstallBinding,private val receipt:OriginalExportReceipt,private val folder:Path,
        private val channel:FileChannel,private val held:FileLock,var checkpoint:ResumeCheckpoint,private val request:String,private val generation:Long,private val selected:String):AutoCloseable {
        private var closed=false;private var appended=false
        fun append(phase:ResumePhase,address:Int?,frontier:Int,commit:Boolean,message:String=""){
            check(!closed);require(appended||phase==ResumePhase.REVIEWED);require(message.length<=1024&&checkpoint.sequence<MAX_RECORDS)
            require(base(binding).digest==checkpoint.baseSha256){"Initial journal changed; recovery blocked"};validate(checkpoint,phase,address,frontier,commit)
            val sequence=checkpoint.sequence+1
            val map=mapOf("schemaVersion" to 1L,"bindingId" to binding.id,"baseSha256" to checkpoint.baseSha256,"exportReceiptSha256" to receipt.sha256,
                "previousSha256" to checkpoint.headSha256,"sequence" to sequence.toLong(),"requestId" to request,"generation" to generation,"selectedDocument" to selected,
                "phase" to phase.name,"address" to address?.toLong(),"frontierPage" to frontier.toLong(),"commitPossible" to commit,"message" to message)
            val bytes=(StrictJson.canonical(map)+"\n").toByteArray();require(bytes.size<=32768)
            val destination=folder.resolve("%08d.json".format(sequence));require(!Files.exists(destination,LinkOption.NOFOLLOW_LINKS))
            val temporary=folder.resolve("${UUID.randomUUID()}.tmp")
            try{
                FileChannel.open(temporary,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE).use{out->val buffer=ByteBuffer.wrap(bytes);while(buffer.hasRemaining())out.write(buffer);out.force(true)}
                Files.move(temporary,destination,StandardCopyOption.ATOMIC_MOVE)
                forceDirectory(folder)
                checkpoint=ResumeCheckpoint(checkpoint.baseSha256,sha256(bytes),sequence,frontier,commit);appended=true
            }finally{Files.deleteIfExists(temporary)}
        }
        override fun close(){if(!closed){closed=true;try{held.release()}finally{channel.close()}}}
    }
}
