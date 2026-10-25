package org.openvimar.updater

import android.util.AtomicFile
import org.json.JSONObject
import java.io.File

/** Each immutable package and its device-specific state survive switching packages. */
internal class SessionFiles(private val directory: File) {
    data class Identity(val digest: String, val address: String,val uid:List<String>?=null)
    private val pointer = AtomicFile(File(directory, "current-session.json"))

    fun current(): Identity? {
        if (!pointer.baseFile.exists() && !File(pointer.baseFile.path + ".bak").exists()) return null
        val json = JSONObject(pointer.openRead().use { it.readBytes().toString(Charsets.UTF_8) })
        return Identity(json.getString("digest"), json.getString("address"),if(json.isNull("uid")) null else json.getJSONArray("uid").let {array->List(array.length()){array.getString(it)}}).also { key(it) }
    }

    fun select(identity: Identity) {
        key(identity)
        val bytes = JSONObject().put("digest", identity.digest).put("address", identity.address).put("uid",identity.uid?.let {org.json.JSONArray(it)} ?: JSONObject.NULL).toString().toByteArray()
        val output = pointer.startWrite()
        try {
            output.write(bytes)
            pointer.finishWrite(output)
        } catch (failure: Throwable) {
            pointer.failWrite(output)
            throw failure
        }
        check(current() == identity) { "Selezione locale non verificabile" }
    }

    fun clearSelection()=pointer.delete()

    fun target(identity:Identity):File=stateFile(identity,"target.json")

    fun bundle(digest: String): File {
        require(Regex("[0-9a-f]{64}").matches(digest))
        return File(directory, "packages/$digest.zip").also { check(it.parentFile!!.mkdirs() || it.parentFile!!.isDirectory) }
    }

    fun checkpoint(identity: Identity): File = stateFile(identity, "checkpoint.json")
    fun report(identity: Identity): File = stateFile(identity, "report.json")

    private fun stateFile(identity: Identity, name: String): File = File(directory, "sessions/${key(identity)}/$name").also {
        check(it.parentFile!!.mkdirs() || it.parentFile!!.isDirectory)
    }

    private fun key(identity: Identity): String {
        require(Regex("[0-9a-f]{64}").matches(identity.digest))
        require(Regex("([0-9A-F]{2}:){5}[0-9A-F]{2}").matches(identity.address))
        require(identity.uid==null || (identity.uid.size==2 && identity.uid.all {Regex("[0-9a-f]{8}").matches(it)}))
        return identity.digest + "-" + identity.address.replace(":", "") + (identity.uid?.joinToString("",prefix="-") ?: "")
    }
}
