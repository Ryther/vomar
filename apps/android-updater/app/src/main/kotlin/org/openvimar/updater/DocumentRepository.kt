package org.openvimar.updater

import android.content.Context
import android.net.Uri
import android.util.AtomicFile
import org.json.JSONObject
import org.json.JSONArray
import org.openvimar.updater.core.*
import java.io.File
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec

/** Exact signed ZIP is stored once per release; runtime target evidence stays outside it. */
class DocumentRepository(private val context:Context,private val verificationKey:java.security.PublicKey?=null) {
    private val files=SessionFiles(context.filesDir)
    private val legacyTarget=AtomicFile(File(context.filesDir,"common-bootstrap-target.json"))
    private val pending=AtomicFile(File(context.filesDir,"common-release.json"))
    private val key by lazy {
        verificationKey ?: KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(context.resources.openRawResource(R.raw.firmware_public).use{it.readBytes()}))
    }
    @Suppress("DEPRECATION")
    private fun appVersion()=context.packageManager.getPackageInfo(context.packageName,0).versionName ?: error("App version unavailable")
    private fun exists(file:AtomicFile)=file.baseFile.exists() || File(file.baseFile.path+".bak").exists()
    private fun write(file:AtomicFile,bytes:ByteArray,checkActive:()->Unit={}) {
        val output=file.startWrite()
        try {checkActive();output.write(bytes);checkActive();file.finishWrite(output)}
        catch(failure:Throwable){file.failWrite(output);throw failure}
    }
    fun pendingCommon():ValidatedCommonPackage? {
        if(!exists(pending)) return null
        val digest=JSONObject(pending.openRead().use{it.readBytes().toString(Charsets.UTF_8)}).getString("digest")
        val raw=AtomicFile(files.bundle(digest)).openRead().use{CommonPackageReader.read(it)}
        require(raw.bundleDigest==digest) {"Common release storage digest mismatch"}
        return CommonPackageValidator.validate(raw,key,appVersion())
    }
    fun current():ValidatedPackage? {
        val identity=files.current() ?: return null
        val imported=AtomicFile(files.bundle(identity.digest))
        if(!exists(imported)) return null
        val bytes=imported.openRead().use{it.readBytes()}
        if(identity.uid==null) return validateLegacy(bytes).also{require(it.bundleDigest==identity.digest && it.manifest.device.bleAddress==identity.address)}
        val common=CommonPackageValidator.validate(CommonPackageReader.read(bytes.inputStream()),key,appVersion())
        val saved=JSONObject(AtomicFile(files.target(identity)).openRead().use{it.readBytes().toString(Charsets.UTF_8)})
        val runtime=RuntimeIdentity(saved.getInt("protocol"),saved.getString("model"),saved.getInt("layoutVersion"),
            saved.getJSONArray("uid").let{array->List(array.length()){array.getString(it)}},saved.getString("loaderSha256"),
            if(saved.isNull("typedLoader"))null else saved.getJSONObject("typedLoader").let{LoaderContract(it.getString("kind"),it.getString("sha256"))},
            if(saved.isNull("anchorSha256"))null else saved.getString("anchorSha256"))
        require(runtime.uid==identity.uid && common.bundleDigest==identity.digest) {"Saved runtime target mismatch"}
        return common.bind(runtime,identity.address)
    }
    fun pendingLegacyTarget():String? {
        if(!exists(legacyTarget))return null
        val json=JSONObject(legacyTarget.openRead().use{it.readBytes().toString(Charsets.UTF_8)})
        require(json.getInt("schemaVersion")==1 && json.getString("identityEvidence")=="not observed")
        require(json.getString("digest")==pendingCommon()?.bundleDigest) {"Legacy target release mismatch"}
        return json.getString("address").also{require(Regex("([0-9A-F]{2}:){5}[0-9A-F]{2}").matches(it))}
    }
    fun selectLegacyBootstrapTarget(address:String,checkActive:()->Unit,commitSelection:(()->Unit)->Unit) {
        val common=pendingCommon() ?: error("Import a common release first")
        require(common.migration!=null && common.manifest.legacyRecoverySignedHashes.isNotEmpty())
        require(Regex("([0-9A-F]{2}:){5}[0-9A-F]{2}").matches(address))
        val json=JSONObject().put("schemaVersion",1).put("digest",common.bundleDigest).put("address",address).put("identityEvidence","not observed")
        checkActive();commitSelection{write(legacyTarget,json.toString().toByteArray());files.clearSelection()}
    }
    fun bindCommonTarget(address:String,runtime:RuntimeIdentity,checkActive:()->Unit={},commitSelection:(()->Unit)->Unit={it()}):ValidatedPackage {
        val common=pendingCommon() ?: error("Import a common signed release first")
        val bound=common.bind(runtime,address)
        val identity=SessionFiles.Identity(common.bundleDigest,address,runtime.uid)
        val json=JSONObject().put("protocol",runtime.protocol).put("model",runtime.model).put("layoutVersion",runtime.layoutVersion)
            .put("uid",JSONArray(runtime.uid)).put("loaderSha256",runtime.loaderSha256).put("observedVia","authenticated BLE identity command")
            .put("typedLoader",runtime.typedLoader?.let{JSONObject().put("kind",it.kind).put("sha256",it.sha256)} ?: JSONObject.NULL)
            .put("anchorSha256",runtime.anchorSha256 ?: JSONObject.NULL)
        checkActive();write(AtomicFile(files.target(identity)),json.toString().toByteArray(),checkActive)
        checkActive();commitSelection{files.select(identity);legacyTarget.delete()}
        return bound
    }
    fun importDocument(uri:Uri,checkActive:()->Unit={},commitSelection:(()->Unit)->Unit={it()}):ValidatedPackage =
        requireNotNull(importAnyDocument(uri,checkActive,commitSelection)) {"Common release imported; choose a Bluetooth target"}
    fun importAnyDocument(uri:Uri,checkActive:()->Unit={},commitSelection:(()->Unit)->Unit={it()}):ValidatedPackage? {
        checkActive();val input=context.contentResolver.openInputStream(uri) ?: error("Document unavailable")
        return importAnyStream(input,checkActive,commitSelection)
    }
    internal fun importStream(source:java.io.InputStream,checkActive:()->Unit={},commitSelection:(()->Unit)->Unit={it()}):ValidatedPackage =
        requireNotNull(importAnyStream(source,checkActive,commitSelection)) {"Common release imported; choose a Bluetooth target"}
    internal fun importAnyStream(source:java.io.InputStream,checkActive:()->Unit={},commitSelection:(()->Unit)->Unit={it()}):ValidatedPackage? {
        val bytes=source.use{input->val output=java.io.ByteArrayOutputStream();val buffer=ByteArray(8192)
            while(true){checkActive();val n=input.read(buffer);checkActive();if(n<0)break;require(n<=PackageReader.MAX_ZIP-output.size()){ "Package too large" };output.write(buffer,0,n)};output.toByteArray()}
        checkActive()
        val raw=CommonPackageReader.read(bytes.inputStream())
        // Dispatch only after bounded archive parsing; each validator authenticates its own schema.
        val version=JSONObject(raw.manifest.toString(Charsets.UTF_8)).getInt("schemaVersion")
        val common=if(version in 2..3)CommonPackageValidator.validate(raw,key,appVersion()) else null
        val legacy=if(version==1)validateLegacy(bytes) else null
        require(common!=null || legacy!=null) {"Unsupported package schema"}
        val digest=common?.bundleDigest ?: requireNotNull(legacy).bundleDigest
        val imported=AtomicFile(files.bundle(digest));write(imported,bytes,checkActive)
        val persisted=imported.openRead().use{it.readBytes()}
        require(java.security.MessageDigest.getInstance("SHA-256").digest(persisted).contentEquals(java.security.MessageDigest.getInstance("SHA-256").digest(bytes))) {"Private package storage verification failed"}
        if(common!=null) {
            CommonPackageValidator.validate(CommonPackageReader.read(persisted.inputStream()),key,appVersion())
            checkActive();commitSelection{write(pending,JSONObject().put("digest",digest).toString().toByteArray());files.clearSelection();legacyTarget.delete()}
        } else {
            validateLegacy(persisted);checkActive();commitSelection{pending.delete();legacyTarget.delete();files.select(SessionFiles.Identity(digest,requireNotNull(legacy).manifest.device.bleAddress))}
        }
        return legacy
    }
    private fun validateLegacy(bytes:ByteArray)=PackageValidator.validate(PackageReader.read(bytes.inputStream()),key,appVersion())
}
