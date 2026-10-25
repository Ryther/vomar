package org.openvimar.updater

import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.*
import org.openvimar.updater.core.*

/** HTTPS bytes must match the signed carrier before a server-side URL is submitted. */
internal class ZigbeeHttpsSource {
    suspend fun verify(source:String,size:Int,expectedSha:String)=withContext(Dispatchers.IO) {
        ZigbeeBridge.requireHttpsSource(source);require(size in 1..ZigbeeCarrierValidator.MAX_CARRIER)
        var location=source
        for(redirect in 0..4) {
            currentCoroutineContext().ensureActive();val connection=URL(location).openConnection() as HttpURLConnection
            try {
                connection.instanceFollowRedirects=false;connection.connectTimeout=15000;connection.readTimeout=15000
                connection.setRequestProperty("Accept","application/octet-stream")
                when(connection.responseCode) {
                    301,302,303,307,308 -> {
                        require(redirect<4);location=URL(URL(location),requireNotNull(connection.getHeaderField("Location"))).toString();ZigbeeBridge.requireHttpsSource(location)
                    }
                    200 -> {
                        require(connection.contentLengthLong<0 || connection.contentLengthLong==size.toLong()) { "Remote carrier size mismatch" }
                        val digest=MessageDigest.getInstance("SHA-256");var total=0
                        connection.inputStream.use { input ->
                            val buffer=ByteArray(8192)
                            while(true) {
                                currentCoroutineContext().ensureActive();val n=input.read(buffer);if(n<0)break
                                require(n<=size-total) { "Remote carrier exceeds signed size" };total+=n;digest.update(buffer,0,n)
                            }
                        }
                        require(total==size && digest.digest().joinToString("") { "%02x".format(it.toInt() and 255) }==expectedSha) { "Remote OTA bytes do not match the signed carrier" }
                        return@withContext
                    }
                    else -> error("HTTPS OTA source unavailable")
                }
            } finally { connection.disconnect() }
        }
        error("HTTPS redirect limit exceeded")
    }
}

/** Queue holds the network lane; this guard also serializes standalone callers. */
internal class ZigbeeFleetExecutor(private val bridge:()->ZigbeeBridge,
    private val loadRelease:suspend(FleetReleaseRef)->ValidatedCommonPackage,
    private val verifyRemote:suspend(String,Int,String)->Unit={url,size,sha -> ZigbeeHttpsSource().verify(url,size,sha)},
    private val updateTimeoutMs:Long=2*60*60*1000L,private val returnTimeoutMs:Long=180000):FleetJobExecutor,FleetJobReconciler {
    private val lanes=java.util.concurrent.ConcurrentHashMap<String,Mutex>()
    private val held=java.util.concurrent.ConcurrentHashMap<String,String>()
    override suspend fun execute(context:FleetExecutionContext,emit:suspend(FleetExecutionEvent)->Unit):FleetExecutionResult {
        val network=context.job.device.networkId ?: return blocked("No Zigbee network selected")
        return lanes.getOrPut(network){Mutex()}.withLock {
            if(held.containsKey(network))blocked("An earlier server-side update remains uncertain on this network · explicitly check its status")
            else executeLocked(context,network,emit)
        }
    }
    private suspend fun executeLocked(context:FleetExecutionContext,network:String,emit:suspend(FleetExecutionEvent)->Unit):FleetExecutionResult=coroutineScope {
        var submitted=false
        try {
            require(context.job.route==FleetRoute.ZIGBEE)
            val ieee=requireNotNull(context.job.device.ieee) { "Exact IEEE target is required" }
            val pkg=loadRelease(context.release)
            require(pkg.bundleDigest==context.release.digest && pkg.manifest.main.signedRegionSha256==context.release.mainHash && pkg.manifest.main.version==context.release.version) { "Selected release changed" }
            val meta=requireNotNull(pkg.manifest.zigbeeOta) { "This release contains no signed Zigbee OTA carrier; use Bluetooth" }
            val bytes=requireNotNull(pkg.zigbeeOta);ZigbeeCarrierValidator.validate(meta,bytes,pkg.manifest.main)
            val ref=requireNotNull(context.release.zigbeeOta) { "Choose a fetchable HTTPS URL for this signed carrier" }
            require(ref.manufacturerCode==meta.manufacturerCode && ref.imageType==meta.imageType && ref.fileVersion==meta.fileVersion && ref.sha256==meta.fileSha256 && ref.size==meta.size.toLong() && ref.model==meta.model && ref.profile==meta.profile) { "Zigbee route differs from the verified release" }
            ZigbeeBridge.requireHttpsSource(ref.source)
            val transport=bridge();transport.requireCustomTarget(network,ieee)
            emit(FleetExecutionEvent(message="Verifying the HTTPS OTA carrier"));verifyRemote(ref.source,meta.size,meta.fileSha256)
            currentCoroutineContext().ensureActive();transport.requireCustomTarget(network,ieee)
            emit(FleetExecutionEvent(message="Checking the selected device with Zigbee2MQTT"))
            val check=transport.check(network,ieee,ref.source)
            require(check.available && check.source==ref.source) { "Bridge did not confirm the selected HTTPS update source" }
            // Subscribe before submission so immediate device reports cannot race the command.
            val watcher=launch(start=CoroutineStart.UNDISPATCHED) {
                transport.observations.collect { observation ->
                    if(observation.networkId==network && observation.ieee==ieee && !observation.retained) {
                        val update=observation.payload["update"] as? JsonObject
                        val progress=(update?.get("progress") as? JsonPrimitive)?.takeUnless { it.isString }?.doubleOrNull
                        if(update?.string("state")=="updating" && progress!=null && progress.isFinite() && progress in 0.0..100.0)
                            emit(FleetExecutionEvent(progress.toInt(),"Zigbee transfer · observed ${progress.toInt()}%"))
                    }
                }
            }
            try {
                currentCoroutineContext().ensureActive();transport.requireCustomTarget(network,ieee)
                transport.verifyRecoveryPair(network,ieee,pkg.manifest.targetRecoverySignedHash)
                emit(FleetExecutionEvent(message="Zigbee update submitted · waiting for device evidence",submissionMayHaveStarted=true))
                submitted=true // Durable queue marker precedes a possibly delivered publish.
                held[network]="${context.groupId}:${context.job.id}"
                val response=transport.update(network,ieee,ref.source,updateTimeoutMs)
                val to=response["to"] as? JsonObject
                require((to?.get("file_version") as? JsonPrimitive)?.takeUnless { it.isString }?.longOrNull==meta.fileVersion) { "Bridge completed a different or unknown file version" }
                val returnedVersion=to.string("software_build_id")
                require(returnedVersion==null || returnedVersion==context.release.version) { "Returned software version differs from the selected release" }
                emit(FleetExecutionEvent(message="Transfer acknowledged · verifying return to target firmware"))
                fun matches(observation:ZigbeeObservation):Boolean {
                    val data=observation.payload
                    val version=data.string("software_build_id") ?: data.string("software_build")
                    val installed=((data["update"] as? JsonObject)?.get("installed_version") as? JsonPrimitive)?.longOrNull
                    return version==context.release.version && (installed==null || installed==meta.fileVersion)
                }
                // The successful response in Z2M2.14.1 follows a fresh post-transfer Basic-cluster read.
                // A matching to.software_build_id is direct return evidence, distinct from file delivery.
                val hasReturn=returnedVersion==context.release.version
                if(!hasReturn)withTimeout(returnTimeoutMs) { transport.observations.first { it.networkId==network && it.ieee==ieee && !it.retained && matches(it) } }
                held.remove(network)
                FleetExecutionResult(FleetJobState.VERIFIED,"Target firmware returned · Zigbee2MQTT reported ${context.release.version}")
            } finally { watcher.cancelAndJoin() }
        } catch(e:TimeoutCancellationException) {
            FleetExecutionResult(if(submitted)FleetJobState.UNCERTAIN_RESET else FleetJobState.BLOCKED,
                if(submitted)"Update outcome not verified · explicitly check status before any further submission" else "Timed out before update submission")
        } catch(e:CancellationException) { throw e }
        catch(e:Exception) {
            FleetExecutionResult(if(submitted)FleetJobState.UNCERTAIN_RESET else FleetJobState.BLOCKED,
                if(submitted)"Update outcome not verified · reconnect and check the selected device" else (e.message ?: "Zigbee prerequisites are not satisfied"))
        }
    }
    override suspend fun reconcile(context:FleetExecutionContext):FleetExecutionResult {
        try {
            val network=requireNotNull(context.job.device.networkId);val ieee=requireNotNull(context.job.device.ieee)
            require(context.job.route==FleetRoute.ZIGBEE)
            require(held[network]==null || held[network]=="${context.groupId}:${context.job.id}") { "Another operation owns the uncertain network" }
            val pkg=loadRelease(context.release)
            require(pkg.bundleDigest==context.release.digest && pkg.manifest.main.signedRegionSha256==context.release.mainHash && pkg.manifest.main.version==context.release.version)
            val meta=requireNotNull(pkg.manifest.zigbeeOta)
            val observation=bridge().inspectOtaState(network,ieee)
            val update=observation.payload["update"] as? JsonObject ?: error("Missing fresh OTA state")
            require(update.string("state") in setOf("idle","available")) { "Device may still have an active/scheduled update" }
            val installed=(update["installed_version"] as? JsonPrimitive)?.takeUnless { it.isString }?.longOrNull
            require(installed!=null && installed in 0..0xffffffffL) { "Missing fresh installed wire version" }
            val software=observation.payload.string("software_build_id")
            if(installed==meta.fileVersion) {
                require(software==null || software==context.release.version)
                held.remove(network)
                return FleetExecutionResult(FleetJobState.VERIFIED,"Fresh selected-device OTA check confirms target file version")
            }
            held.remove(network)
            return FleetExecutionResult(FleetJobState.PAUSED,"Fresh selected-device check confirms idle with another firmware version · explicit start required")
        } catch(e:TimeoutCancellationException) { /* Bounded check could not establish a safe outcome. */ }
        catch(e:CancellationException) { throw e }
        catch(_:Exception) { /* Unknown evidence retains the durable network lease. */ }
        return FleetExecutionResult(FleetJobState.UNCERTAIN_RESET,"No fresh correlated idle/target evidence · network update remains held")
    }
    private fun blocked(message:String)=FleetExecutionResult(FleetJobState.BLOCKED,message)
}
