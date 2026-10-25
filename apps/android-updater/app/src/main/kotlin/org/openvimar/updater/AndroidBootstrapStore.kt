package org.openvimar.updater

import android.util.AtomicFile
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import org.json.JSONObject
import org.json.JSONArray
import org.openvimar.updater.core.*
import kotlinx.serialization.json.Json

/** Separate namespace: an address-only legacy bridge is never a UID-verified update session. */
internal class AndroidBootstrapStore(private val directory:File):BootstrapStore {
    private fun file(digest:String,address:String):AtomicFile {
        require(Regex("[0-9a-f]{64}").matches(digest) && Regex("([0-9A-F]{2}:){5}[0-9A-F]{2}").matches(address))
        val target=File(directory,"common-bootstrap/$digest-${address.replace(":","")}.json")
        check(target.parentFile!!.mkdirs() || target.parentFile!!.isDirectory)
        return AtomicFile(target)
    }
    override suspend fun load(digest:String,address:String):BootstrapCheckpoint?=withContext(Dispatchers.IO){read(digest,address)}
    @Synchronized private fun read(digest:String,address:String):BootstrapCheckpoint? {
        val file=file(digest,address)
        if(!file.baseFile.exists() && !File(file.baseFile.path+".bak").exists())return null
        val json=JSONObject(file.openRead().use{it.readBytes().toString(Charsets.UTF_8)})
        require(json.getInt("schemaVersion")==1 && json.getString("kind")=="common-legacy-bootstrap")
        val uid=if(json.isNull("observedUid"))null else json.getJSONArray("observedUid").let{array->List(array.length()){array.getString(it)}}
        require(uid==null || uid.size==2 && uid.all{Regex("[0-9a-f]{8}").matches(it)})
        val observed=if(json.isNull("observedIdentity"))null else Json.decodeFromString<RuntimeIdentity>(json.getJSONObject("observedIdentity").toString()).also(RuntimeIdentityLookup::validate)
        return BootstrapCheckpoint(json.getString("bundleDigest"),json.getString("address"),BootstrapPhase.valueOf(json.getString("phase")),json.getInt("ackOffset"),json.getBoolean("resetAcknowledged"),uid,observed).also {
            require(it.bundleDigest==digest && it.address==address && it.ackOffset>=0)
        }
    }
    override suspend fun save(checkpoint:BootstrapCheckpoint)=withContext(Dispatchers.IO){write(checkpoint)}
    @Synchronized private fun write(checkpoint:BootstrapCheckpoint) {
        val file=file(checkpoint.bundleDigest,checkpoint.address)
        val json=JSONObject().put("schemaVersion",1).put("kind","common-legacy-bootstrap")
            .put("identityEvidence",if(checkpoint.observedUid==null)"address and authenticated bond; UID/loader not observed" else "runtime UID observed after target recovery")
            .put("bundleDigest",checkpoint.bundleDigest).put("address",checkpoint.address).put("phase",checkpoint.phase.name)
            .put("ackOffset",checkpoint.ackOffset).put("resetAcknowledged",checkpoint.resetAcknowledged)
            .put("observedUid",checkpoint.observedUid?.let{JSONArray(it)} ?: JSONObject.NULL)
            .put("observedIdentity",checkpoint.observedIdentity?.let{JSONObject(Json.encodeToString(RuntimeIdentity.serializer(),it))} ?: JSONObject.NULL)
        val output=file.startWrite()
        try {output.write(json.toString().toByteArray());file.finishWrite(output)}catch(e:Throwable){file.failWrite(output);throw e}
        check(read(checkpoint.bundleDigest,checkpoint.address)==checkpoint) {"Bootstrap checkpoint readback failed"}
    }
    fun reportFile(digest:String,address:String):File=file(digest,address).baseFile.let{File(it.parentFile,it.nameWithoutExtension+"-report.json")}
    suspend fun report(digest:String,address:String,outcome:String)=withContext(Dispatchers.IO){writeReport(digest,address,outcome)}
    @Synchronized private fun writeReport(digest:String,address:String,outcome:String) {
        val checkpoint=read(digest,address)
        val json=JSONObject().put("kind","common-legacy-bootstrap").put("releaseDigest",digest).put("address",address)
            .put("identityEvidence",if(checkpoint?.observedUid==null)"authenticated address and exact signed source images; UID/loader not observed" else "runtime UID observed after target recovery")
            .put("observedUid",checkpoint?.observedUid?.let{JSONArray(it)} ?: JSONObject.NULL)
            .put("phase",checkpoint?.phase?.name ?: JSONObject.NULL).put("ackOffset",checkpoint?.ackOffset ?: 0)
            .put("resetAcknowledged",checkpoint?.resetAcknowledged ?: false).put("outcome",outcome)
            .put("mainFirmwareInstalled",false).put("androidApi",android.os.Build.VERSION.SDK_INT)
        val file=AtomicFile(reportFile(digest,address));val output=file.startWrite()
        try{output.write(json.toString(2).toByteArray());file.finishWrite(output)}catch(e:Throwable){file.failWrite(output);throw e}
    }

}
