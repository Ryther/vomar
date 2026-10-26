package org.openvimar.updater.installer

import android.content.Context
import android.util.AtomicFile
import org.json.JSONObject
import org.openvimar.installer.*
import java.io.File
import java.io.InputStream
import java.nio.file.Path
import java.time.Instant

/** App-private immutable originals and diagnostic metadata. Journals remain the
 * separate strict engine evidence; this JSON never grants resume authority. */
internal class AndroidInitialInstallPersistence(private val context:Context):InitialInstallPersistence {
    private val files=context.filesDir.apply{DurableInstallFiles.ensureDirectory(toPath())}
    private val directory=File(files,"dk-first-install").apply{DurableInstallFiles.ensureDirectory(toPath())}
    private val originals=File(directory,"originals").apply{DurableInstallFiles.ensureDirectory(toPath())}
    val journalDirectory:Path=File(directory,"transactions").toPath()
    private val status=AtomicFile(File(directory,"status.json"))
    private val retained by lazy{InitialInstallRetainedEvidence(directory.toPath(),{hash->
        val file=original(hash)
        if(file.baseFile.exists()||File(file.baseFile.path+".bak").exists())reopenOriginal(hash) else null
    })}
    val resumeJournal get()=retained.journal
    @Synchronized fun resumeOptions(target:TargetIdentity)=retained.options(target)
    @Synchronized fun reopenRetained(bindingId:String)=retained.reopen(bindingId)
    @Synchronized override fun saveExportReceipt(original:OriginalMaterial,binding:InstallBinding)=retained.saveExport(original,binding)
    @Synchronized override fun recordStart(binding:InstallBinding,requestId:String,acknowledged:Boolean)=retained.recordStart(binding,requestId,acknowledged)
    override fun assertCanCapture(target:TargetIdentity)=FileInstallRecoveryFence(journalDirectory).assertCanCapture(target)
    private fun original(hash:String):AtomicFile {require(Regex("[0-9a-f]{64}").matches(hash));return AtomicFile(File(originals,"$hash.zip"))}
    private fun read(input:InputStream,limit:Int):ByteArray=input.use{stream->
        val out=java.io.ByteArrayOutputStream();val b=ByteArray(8192)
        while(true){val n=stream.read(b);if(n<0)break;require(n>0&&out.size()+n<=limit);out.write(b,0,n)};out.toByteArray()}
    private fun write(file:AtomicFile,bytes:ByteArray){
        val output=file.startWrite()
        try{output.write(bytes);output.flush();output.fd.sync();file.finishWrite(output);DurableInstallFiles.syncDirectory(file.baseFile.parentFile!!.toPath())}
        catch(error:Exception){file.failWrite(output);throw error}
    }
    @Synchronized override fun saveOriginal(requestId:String,archive:ByteArray){
        require(java.util.UUID.fromString(requestId).toString()==requestId)
        val checked=OriginalArchive.verify(archive);val file=original(checked.archiveSha256)
        if(file.baseFile.exists()||File(file.baseFile.path+".bak").exists()){
            require(read(file.openRead(),SelectedDocumentExport.MAX).contentEquals(archive)){"Existing original evidence differs; never overwrite"}
        }else write(file,archive)
        // A prior rename may have succeeded while its parent sync failed.
        // Exact-existing retries must establish that directory durability too.
        DurableInstallFiles.syncDirectory(originals.toPath())
        require(reopenOriginal(checked.archiveSha256).archiveSha256==checked.archiveSha256)
    }
    @Synchronized fun reopenOriginal(hash:String):VerifiedOriginal {
        val checked=OriginalArchive.verify(read(original(hash).openRead(),SelectedDocumentExport.MAX))
        require(checked.archiveSha256==hash){"Private original filename/content mismatch"};return checked
    }
    /** Reopen the immutable private file through the same byte-exact handoff
     * used by external exports. This receipt is evidence, never approval. */
    fun privateExport(hash:String)=object:ArchiveExport {
        override fun create(bytes:ByteArray):String {
            val retained=read(original(hash).openRead(),SelectedDocumentExport.MAX)
            require(retained.contentEquals(bytes)){"Private backup changed"}
            return original(hash).baseFile.toURI().toString()
        }
        override fun reopen(document:String):ByteArray {
            require(document==original(hash).baseFile.toURI().toString())
            return read(original(hash).openRead(),SelectedDocumentExport.MAX)
        }
    }
    @Synchronized fun originalBytes(hash:String):ByteArray {
        reopenOriginal(hash);return read(original(hash).openRead(),SelectedDocumentExport.MAX)
    }
    /** Organisational version evidence is invalid after an exact original
     * restore. Preserve names, rooms and transport mappings for the same UID. */
    @Synchronized fun recordOriginalRestored(hash:String){
        val target=reopenOriginal(hash).identity;val expected=listOf("%08x".format(target.uid0),"%08x".format(target.uid1))
        val prefs=context.getSharedPreferences("fleet-ui",Context.MODE_PRIVATE)
        val rows=org.json.JSONArray(prefs.getString("devices","[]"))
        for(i in 0 until rows.length()){
            val row=rows.getJSONObject(i);val uid=row.optJSONArray("uid")?:continue
            if(List(uid.length()){uid.getString(it).lowercase().removePrefix("0x").padStart(8,'0')}==expected)
                row.put("installedVersion","").put("firmwareKind","UNKNOWN").put("observedAt",JSONObject.NULL).put("observationSource","")
        }
        check(prefs.edit().putString("devices",rows.toString()).commit()){"Original restored, but saved version could not be cleared"}
    }
    @Synchronized fun allBackups():List<VerifiedOriginal> = originals.listFiles().orEmpty()
        .filter{it.name.matches(Regex("[0-9a-f]{64}\\.zip"))}.mapNotNull{file->
            runCatching{reopenOriginal(file.name.removeSuffix(".zip"))}.getOrNull()
        }
    fun backupsFor(uid:List<String>)=allBackups().filter{it.identity.let{target->listOf("%08x".format(target.uid0),"%08x".format(target.uid1))}==uid.map{it.lowercase().removePrefix("0x").padStart(8,'0')}}

    @Synchronized override fun saveState(snapshot:InitialInstallSnapshot){
        val r=snapshot.request;val b=snapshot.binding
        val report=JSONObject().put("type","dk-first-install").put("schemaVersion",1).put("recordedAt",Instant.now().toString())
            .put("phase",snapshot.phase.name).put("requestId",r?.requestId?:JSONObject.NULL)
            .put("candidate",snapshot.candidate).put("resume",snapshot.resume)
            .put("resumeHeadSha256",snapshot.resumeHeadSha256?:JSONObject.NULL).put("resumeFrontierPage",snapshot.resumeFrontierPage?:JSONObject.NULL)
            .put("resumeClassification",snapshot.resumeClassification?:JSONObject.NULL)
            .put("releaseSha256",r?.reviewedReleaseSha256?:JSONObject.NULL).put("deviceName",r?.deviceName?:JSONObject.NULL)
            .put("allowResetCatch",r?.allowResetCatch?:false).put("resetCatchUsed",snapshot.resetCatchUsed)
            .put("archiveSha256",snapshot.archiveSha256?:JSONObject.NULL).put("exportedDocument",snapshot.exportedDocument?:JSONObject.NULL)
            .put("mutationMayHaveStarted",snapshot.mutationMayHaveStarted).put("commitMayHaveBeenWritten",snapshot.commitMayHaveBeenWritten)
            .put("journalFailure",snapshot.journalFailure).put("cpuDisposition",snapshot.cpuDisposition).put("message",snapshot.message.take(1024))
            .put("debugStateUncertain",snapshot.debugStateUncertain)
            .put("programmingPreparation",snapshot.programmingPreparation?:JSONObject.NULL)
            .put("installStep",snapshot.installStep?:JSONObject.NULL).put("installAddress",snapshot.installAddress?:JSONObject.NULL)
            .put("watchdogHandoff",snapshot.watchdogHandoff?:JSONObject.NULL)
            .put("watchdog",snapshot.watchdog?.let{JSONObject(it.asContract())}?:JSONObject.NULL)
            .put("autoResume",false).put("hardwareQualified",false)
        r?.target?.let{t->report.put("target",JSONObject().put("uid0",t.uid0).put("uid1",t.uid1).put("variant",t.variant).put("part",t.part)
            .put("flashSize",t.flashSize).put("pageSize",t.pageSize).put("ramSize",t.ramSize).put("uicrSize",t.uicrSize))}
        b?.let{report.put("binding",JSONObject().put("id",it.id).put("archiveSha256",it.archiveSha256).put("releaseSha256",it.releaseSha256)
            .put("familySha256",it.familySha256).put("anchorSha256",it.anchorSha256).put("tableSha256",it.tableSha256)
            .put("bodySha256",it.bodySha256).put("installedSha256",it.installedSha256))}
        val bytes=report.toString().toByteArray(Charsets.UTF_8);require(bytes.size<=65536);write(status,bytes)
    }
    @Synchronized fun diagnostic():JSONObject {
        if(!status.baseFile.exists()&&!File(status.baseFile.path+".bak").exists())return JSONObject().put("type","dk-first-install").put("message","No first-install report is available")
        return try{JSONObject(String(read(status.openRead(),65536),Charsets.UTF_8))}
        catch(_:Exception){JSONObject().put("type","dk-first-install").put("message","Stored diagnostic is unreadable; retained journals require review")
            .put("cpuDisposition","unknown").put("mutationMayHaveStarted",true).put("autoResume",false)}
    }
}
