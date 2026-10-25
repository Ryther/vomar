package org.openvimar.updater.installer

import org.openvimar.installer.*
import org.openvimar.installer.resume.*
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.Path

/** Retained per-attempt journals are recovery evidence, never resume authority.
 * Prevent a process restart/new archive digest from relabeling mixed FLASH as
 * a fresh original for the same silicon. Unknown evidence fails closed. */
internal class FileInstallRecoveryFence(private val directory:Path) {
    fun assertCanCapture(target:TargetIdentity){
        val root=requireNotNull(directory.toAbsolutePath().normalize().parent)
        val resumeRoot=root.resolve("resume");val resumeHeads=mutableMapOf<String,ResumeCheckpoint>()
        if(Files.exists(resumeRoot,LinkOption.NOFOLLOW_LINKS)){
            require(Files.isDirectory(resumeRoot,LinkOption.NOFOLLOW_LINKS)){"Resume evidence directory is invalid"};var count=0
            Files.newDirectoryStream(resumeRoot).use{entries->for(folder in entries){
                require(++count<=1024);val id=folder.fileName.toString()
                require(Regex("[0-9a-f]{64}").matches(id)&&Files.isDirectory(folder,LinkOption.NOFOLLOW_LINKS)){"Unknown resume evidence"}
                val record=requireNotNull(FileInstallJournal(directory).load(id)){"Resume has no readable initial journal; fresh original capture is blocked"}
                val path=root.resolve("exports").resolve("$id.json")
                require(Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)&&Files.size(path) in 1..32768){"Resume initial export receipt is missing or invalid"}
                val bytes=Files.newInputStream(path).use{input->val out=java.io.ByteArrayOutputStream();val buffer=ByteArray(2048)
                    while(true){val n=input.read(buffer);if(n<0)break;require(n>0&&out.size()+n<=32768);out.write(buffer,0,n)};out.toByteArray()}
                val receipt=OriginalExportReceipt.parse(bytes)
                resumeHeads[id]=FileResumeJournal(directory,resumeRoot).inspect(record.binding,receipt)
            }}
        }
        if(!Files.exists(directory,LinkOption.NOFOLLOW_LINKS))return
        require(Files.isDirectory(directory,LinkOption.NOFOLLOW_LINKS)){"Installation journal directory is invalid"}
        val store=FileInstallJournal(directory);var count=0
        Files.newDirectoryStream(directory).use{entries->for(file in entries){
            require(++count<=1024){"Too many retained installation records; explicit review required"}
            val name=file.fileName.toString()
            if(Regex("[0-9a-f]{64}-[0-9a-f-]{36}\\.tmp").matches(name))continue // Never delete incomplete evidence.
            require(Regex("[0-9a-f]{64}\\.json").matches(name)){"Unknown installation journal evidence"}
            val record=requireNotNull(store.load(name.removeSuffix(".json")))
            val sameUid=record.binding.target.uid0==target.uid0&&record.binding.target.uid1==target.uid1
            val head=resumeHeads[record.binding.id]
            val anyMutation=record.mutationMayHaveStarted||head?.let{it.frontierPage>=0||it.commitPossible}==true
            require(!sameUid||!anyMutation){"Prior installation for this UID requires the protected original and explicit resume/repair; fresh capture/install is blocked"}
        }}
    }
}
