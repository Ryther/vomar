package org.openvimar.updater

import android.content.Context
import android.net.Uri
import java.io.File
import java.security.KeyFactory
import java.security.PublicKey
import java.security.spec.X509EncodedKeySpec
import kotlinx.coroutines.*
import org.openvimar.installer.CandidateRelease
import org.openvimar.installer.InspectedCommonCandidate
import org.openvimar.updater.core.PackageReader

/** App-private inspection only. No selected fleet release, remembered approval,
 * hardware operation, or executable conversion belongs to this cache owner. */
internal class AndroidBenchCandidates(context:Context,verificationKey:PublicKey?=null) {
    private val app=context.applicationContext
    private val key by lazy {verificationKey ?: KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(app.resources.openRawResource(R.raw.firmware_public).use{it.readBytes()}))}
    private fun appVersion()=app.packageManager.getPackageInfo(app.packageName,0).versionName ?: error("App version unavailable")
    private val cache=BenchCandidateCache(File(app.filesDir,"bench-candidates"),PackageReader.MAX_ZIP){bytes->
        val inspected=CandidateRelease.inspect(bytes,key,appVersion())
        BenchCandidateRef(inspected.releaseSha256,inspected.familySha256,"")
    }
    suspend fun importLocal(uri:Uri,onProgress:(Long)->Unit={}):BenchCandidateRef=withContext(Dispatchers.IO) {
        val coroutine=currentCoroutineContext();coroutine.ensureActive()
        val input=app.contentResolver.openInputStream(uri) ?: error("Candidate document unavailable")
        input.use{cache.import(it,{coroutine.ensureActive()},onProgress)}.also{coroutine.ensureActive()}
    }
    suspend fun inspect(reference:BenchCandidateRef):InspectedCommonCandidate=withContext(Dispatchers.IO) {
        val coroutine=currentCoroutineContext()
        val bytes=cache.read(reference){coroutine.ensureActive()};coroutine.ensureActive()
        CandidateRelease.inspect(bytes,key,appVersion()).also{candidate->
            coroutine.ensureActive()
            require(candidate.releaseSha256==reference.digest&&candidate.familySha256==reference.familySha256){"Inspected candidate reference changed"}
        }
    }
    suspend fun inspectBleTrial(reference:BenchCandidateRef):org.openvimar.updater.core.BleTrialCandidate=withContext(Dispatchers.IO) {
        val coroutine=currentCoroutineContext()
        val bytes=cache.read(reference){coroutine.ensureActive()};coroutine.ensureActive()
        org.openvimar.updater.core.BleTrialCandidate.inspect(bytes,key,appVersion()).also {
            coroutine.ensureActive();require(it.digest==reference.digest&&it.familySha256==reference.familySha256){"Candidate reference changed"}
        }
    }

}
