package org.openvimar.updater

import android.util.AtomicFile
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.openvimar.updater.core.Checkpoint
import org.openvimar.updater.core.Phase
import org.openvimar.updater.core.SessionStore
import org.openvimar.updater.core.RuntimeIdentity
import org.openvimar.updater.core.RuntimeIdentityLookup
import kotlinx.serialization.json.Json
import org.json.JSONObject
import java.io.File

class AndroidSessionStore(directory: File) : SessionStore {
    private val files = SessionFiles(directory)

    @Synchronized fun read(): Checkpoint? {
        val identity = files.current() ?: return null
        return read(identity)
    }

    @Synchronized private fun read(identity: SessionFiles.Identity): Checkpoint? {
        val atomic = AtomicFile(files.checkpoint(identity))
        if (!atomic.baseFile.exists() && !File(atomic.baseFile.path + ".bak").exists()) return null
        val json = JSONObject(atomic.openRead().use { it.readBytes().toString(Charsets.UTF_8) })
        require(json.getInt("schemaVersion") == 1) { "Checkpoint non supportato" }
        return Checkpoint(
            json.getInt("schemaVersion"), json.getString("bundleDigest"),
            json.getString("bleAddress"), Phase.valueOf(json.getString("phase")),
            json.getInt("ackOffset"), json.getBoolean("resetAcknowledged"),
            if(json.isNull("targetUid")) null else json.getJSONArray("targetUid").let { array -> List(array.length()){array.getString(it)} },
            if(json.isNull("runtimeIdentity"))null else Json.decodeFromString<RuntimeIdentity>(json.getJSONObject("runtimeIdentity").toString()).also(RuntimeIdentityLookup::validate)
        ).also {
            require(Regex("[0-9a-f]{64}").matches(it.bundleDigest))
            require(Regex("([0-9A-F]{2}:){5}[0-9A-F]{2}").matches(it.bleAddress))
            require(it.ackOffset >= 0)
            require(it.targetUid?.let {uid -> uid.size==2 && uid.all {word -> Regex("[0-9a-f]{8}").matches(word)} } != false)
            require(it.targetUid==identity.uid) {"Session target UID mismatch"}
            require(it.bundleDigest == identity.digest && it.bleAddress == identity.address) { "Sessione diversa dal pacchetto" }
        }
    }

    override suspend fun load(bundleDigest: String, address: String): Checkpoint? = withContext(Dispatchers.IO) {
        read(SessionFiles.Identity(bundleDigest, address))
    }

    override suspend fun load(bundleDigest:String,address:String,targetUid:List<String>?):Checkpoint? = withContext(Dispatchers.IO) {
        read(SessionFiles.Identity(bundleDigest,address,targetUid))
    }

    override suspend fun save(checkpoint: Checkpoint) = withContext(Dispatchers.IO) { write(checkpoint) }

    @Synchronized private fun write(checkpoint: Checkpoint) {
        val json = JSONObject().put("schemaVersion", checkpoint.schemaVersion)
            .put("bundleDigest", checkpoint.bundleDigest).put("bleAddress", checkpoint.bleAddress)
            .put("phase", checkpoint.phase.name).put("ackOffset", checkpoint.ackOffset)
            .put("resetAcknowledged", checkpoint.resetAcknowledged)
            .put("targetUid",checkpoint.targetUid?.let {org.json.JSONArray(it)} ?: JSONObject.NULL)
            .put("runtimeIdentity",checkpoint.runtimeIdentity?.let{JSONObject(Json.encodeToString(RuntimeIdentity.serializer(),it))} ?: JSONObject.NULL)
        val identity = SessionFiles.Identity(checkpoint.bundleDigest, checkpoint.bleAddress,checkpoint.targetUid)
        val atomic = AtomicFile(files.checkpoint(identity))
        val output = atomic.startWrite()
        try {
            output.write(json.toString().toByteArray())
            atomic.finishWrite(output)
        } catch (failure: Throwable) {
            atomic.failWrite(output)
            throw failure
        }
        check(read(identity) == checkpoint) { "Checkpoint non verificabile su disco" }
    }
}
