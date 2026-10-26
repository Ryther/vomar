package org.openvimar.updater

import android.content.Context
import android.net.Uri
import kotlinx.coroutines.*
import org.json.JSONObject
import org.openvimar.updater.core.*
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec

/** App-private verified release source, independent of currently selected BLE target. */
internal class AndroidFleetReleases(context:Context) {
    private val app=context.applicationContext
    private val preferences=app.getSharedPreferences("fleet-releases",Context.MODE_PRIVATE)
    private val directory=File(app.filesDir,"fleet-releases")
    private val cache=FleetReleaseCache(directory,PackageReader.MAX_ZIP){file->reference(validate(file),file)}
    private val key by lazy {KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(app.resources.openRawResource(R.raw.firmware_public).use{it.readBytes()}))}
    private fun appVersion()=app.packageManager.getPackageInfo(app.packageName,0).versionName ?: error("App version unavailable")
    private fun validate(file:File)=file.inputStream().use{CommonPackageValidator.validate(CommonPackageReader.read(it),key,appVersion())}
    private fun reference(pkg:ValidatedCommonPackage,file:File):FleetReleaseRef {
        return FleetReleaseRef(pkg.bundleDigest,pkg.manifest.main.version,pkg.manifest.main.signedRegionSha256,file.canonicalPath,
            schemaVersion=pkg.manifest.schemaVersion,zigbeeOta=pkg.manifest.zigbeeOta?.let{o->ZigbeeOtaReference(o.manufacturerCode,o.imageType,o.fileVersion,o.fileSha256,o.size.toLong(),o.model,o.profile,"")},targetRecoveryHash=pkg.manifest.targetRecoverySignedHash)
    }
    fun selected():FleetReleaseRef? {
        val digest=preferences.getString("selected",null) ?: return null
        require(Regex("[0-9a-f]{64}").matches(digest))
        val file=File(directory,"$digest.zip");val pkg=validate(file)
        require(pkg.bundleDigest==digest)
        return reference(pkg,file).let{ref->ref.copy(zigbeeOta=ref.zigbeeOta?.copy(source=preferences.getString("ota-$digest","") ?: ""))}
    }
    fun load(ref:FleetReleaseRef):ValidatedCommonPackage = validate(cache.file(ref)).also{pkg->
        require(pkg.bundleDigest==ref.digest&&pkg.manifest.main.version==ref.version&&pkg.manifest.main.signedRegionSha256==ref.mainHash){"Immutable release metadata mismatch"}
        require(pkg.manifest.schemaVersion==ref.schemaVersion){"Immutable release schema reference mismatch"}
        require(ref.targetRecoveryHash==null||ref.targetRecoveryHash==pkg.manifest.targetRecoverySignedHash){"Immutable target recovery reference mismatch"}
    }
    /** Adopt an already independently verified common document without changing
     * the currently bound single-device session or requiring registry data. */
    fun adoptCurrentCommon():FleetReleaseRef? {
        val common=DocumentRepository(app).pendingCommon() ?: return null
        val files=SessionFiles(app.filesDir)
        return select(cache.import(files.bundle(common.bundleDigest).inputStream()))
    }
    private fun select(ref:FleetReleaseRef):FleetReleaseRef {
        check(preferences.edit().putString("selected",ref.digest).commit()){"Could not persist selected release"};return ref
    }
    suspend fun importLocal(uri:Uri):FleetReleaseRef=withContext(Dispatchers.IO){
        val coroutine=currentCoroutineContext();val input=app.contentResolver.openInputStream(uri) ?: error("Release document unavailable")
        val ref=cache.import(input,{coroutine.ensureActive()});coroutine.ensureActive();select(ref)
    }
    suspend fun fetchLatest(repository:String,onProgress:(Long)->Unit={},onTotal:(Long)->Unit={}):FleetReleaseRef=withContext(Dispatchers.IO){
        val repo=ReleaseSource.parse(repository) ?: error("Use a public GitHub owner/repository")
        val coroutine=currentCoroutineContext()
        val json=download("https://api.github.com/repos/$repo/releases/latest",2*1024*1024){input->
            val out=java.io.ByteArrayOutputStream();val b=ByteArray(8192)
            while(true){coroutine.ensureActive();val n=input.read(b);if(n<0)break;require(n<=2*1024*1024-out.size());out.write(b,0,n)}
            JSONObject(out.toString("UTF-8"))
        }
        require(!json.optBoolean("draft")&&!json.optBoolean("prerelease")){"A stable published release is required"}
        val assets=json.getJSONArray("assets")
        val candidates=(0 until assets.length()).map{assets.getJSONObject(it)}.filter{it.getString("name").endsWith(".zip",true)&&it.optLong("size",0) in 1..PackageReader.MAX_ZIP.toLong()}
        require(candidates.size==1){"Choose a local common ZIP: this release does not have exactly one bounded ZIP asset"}
        val asset=candidates.single();onTotal(asset.getLong("size"));onProgress(0);val url=asset.getString("browser_download_url")
        require(URL(url).host=="github.com"&&URL(url).path.startsWith("/$repo/releases/download/")){"Unexpected GitHub asset URL"}
        val ref=download(url,PackageReader.MAX_ZIP){cache.import(it,{coroutine.ensureActive()},onProgress)}
        coroutine.ensureActive();select(ref)
        // Optional carrier location is chosen only after exact-byte verification.
        val ota=ref.zigbeeOta
        if(ota!=null) {
            val matching=(0 until assets.length()).map{assets.getJSONObject(it)}.filter{it.getString("name").endsWith(".ota",true)&&it.optLong("size",-1)==ota.size}
            if(matching.size==1) return@withContext setOtaSource(ref,matching.single().getString("browser_download_url"))
        }
        ref
    }
    suspend fun setOtaSource(ref:FleetReleaseRef,url:String):FleetReleaseRef=withContext(Dispatchers.IO){
        val pkg=load(ref);val metadata=pkg.manifest.zigbeeOta ?: error("This signed release contains no Zigbee OTA carrier")
        val coroutine=currentCoroutineContext()
        val hash=java.security.MessageDigest.getInstance("SHA-256");var count=0L
        download(url,metadata.size){input->val b=ByteArray(8192)
            while(true){coroutine.ensureActive();val n=input.read(b);if(n<0)break;require(n<=metadata.size-count);hash.update(b,0,n);count+=n}
        }
        val measured=hash.digest().joinToString(""){"%02x".format(it.toInt() and 255)}
        require(count==metadata.size.toLong()&&measured==metadata.fileSha256){"OTA URL does not serve the exact publisher-bound carrier"}
        coroutine.ensureActive();check(preferences.edit().putString("ota-${ref.digest}",url).commit())
        ref.copy(zigbeeOta=ZigbeeOtaReference(metadata.manufacturerCode,metadata.imageType,metadata.fileVersion,metadata.fileSha256,metadata.size.toLong(),metadata.model,metadata.profile,url))
    }
    private fun <T> download(url:String,limit:Int,read:(java.io.InputStream)->T):T {
        var current=url
        repeat(5){
            val parsed=URL(current);require(parsed.protocol=="https"&&parsed.userInfo==null&&parsed.ref==null){"Only HTTPS public release URLs are accepted"}
            val connection=parsed.openConnection() as HttpURLConnection
            connection.connectTimeout=5000;connection.readTimeout=2000;connection.instanceFollowRedirects=false
            connection.setRequestProperty("Accept","application/vnd.github+json, application/octet-stream")
            try {
                val code=connection.responseCode
                if(code in listOf(301,302,303,307,308)){current=URL(parsed,connection.getHeaderField("Location") ?: error("Missing redirect location")).toString()}
                else {require(code==200){"Release download returned HTTP $code"};require(connection.contentLengthLong<=limit){"Release download exceeds supported size"}
                    return connection.inputStream.use(read)}
            } finally {connection.disconnect()}
        }
        error("Too many release download redirects")
    }
}
