package org.openvimar.updater.core

import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.serialization.Serializable

@Serializable enum class BootstrapPhase { UPLOAD_MIGRATION, RESET_INTENT, BOUND }
/** Before adoption there is deliberately no UID/loader claim. This is not a normal update checkpoint. */
@Serializable data class BootstrapCheckpoint(val bundleDigest:String,val address:String,val phase:BootstrapPhase,val ackOffset:Int=0,
    val resetAcknowledged:Boolean=false,val observedUid:List<String>?=null,val observedIdentity:RuntimeIdentity?=null)
interface BootstrapStore {
    suspend fun load(digest:String,address:String):BootstrapCheckpoint?
    suspend fun save(checkpoint:BootstrapCheckpoint)
}
class IdentityCommandUnavailable:Exception("Runtime identity command unsupported by this legacy recovery")
/** Only the shared, self-authorizing MIGRATION may run before live identity exists. */
class CommonBootstrapCoordinator(private val wait:suspend(Long)->Unit={delay(it)}) {
    private val mutex=Mutex()
    @Volatile private var stopped=false
    fun stop(){stopped=true}
    private class Stopped:Exception()
    private suspend fun running(){currentCoroutineContext().ensureActive();if(stopped)throw Stopped()}
    companion object {
        fun matches(pkg:ValidatedCommonPackage,address:String,c:BootstrapCheckpoint):Boolean {
            if(c.bundleDigest!=pkg.bundleDigest||c.address!=address||c.ackOffset !in 0..(pkg.migration?.size ?: 0)||
                (c.phase==BootstrapPhase.BOUND)!=(c.observedUid!=null)||c.observedUid?.let{it.size!=2||it.any{word->!Regex("[0-9a-f]{8}").matches(word)}}==true)return false
            if(pkg.manifest.schemaVersion==3&&c.phase==BootstrapPhase.BOUND&&c.observedIdentity==null)return false
            c.observedIdentity?.let{identity->
                if(c.phase!=BootstrapPhase.BOUND||identity.uid!=c.observedUid)return false
                try{CommonPackageValidator.compatibleIdentity(pkg.manifest,identity)}catch(_:IllegalArgumentException){return false}
            }
            return true
        }
        fun eligible(pkg:ValidatedCommonPackage,address:String,remote:RemoteImages,c:BootstrapCheckpoint?):Boolean {
            val migration=pkg.manifest.migration ?: return false
            if(pkg.migration==null || migration.role!="MIGRATION" || remote.recovery.hash !in pkg.manifest.legacyRecoverySignedHashes || !remote.recovery.active || !remote.recovery.bootable) return false
            if(c!=null && (!matches(pkg,address,c) || c.observedUid!=null)) return false
            val primary=remote.primary
            return when {
                primary==null || primary.hash==null -> c?.phase==BootstrapPhase.UPLOAD_MIGRATION
                !primary.bootable -> false
                primary.hash in pkg.manifest.allowedSourceSignedHashes -> true
                primary.hash==migration.signedRegionSha256 -> c!=null
                else -> false
            }
        }
    }
    suspend fun run(pkg:ValidatedCommonPackage,address:String,transport:BleTransport,store:BootstrapStore,
        onBound:suspend(RuntimeIdentity)->Unit,allowResetRetry:Boolean=false,validateIdentity:(RuntimeIdentity)->Unit={},onEvent:suspend(UpdateEvent)->Unit) {
        check(mutex.tryLock()) {"A recovery preparation is already running"};stopped=false
        var checkpoint:BootstrapCheckpoint?=null
        var retries=0;var resetRetryUsed=false;var resetRetryAuthorized=false
        suspend fun save(c:BootstrapCheckpoint){running();store.save(c);checkpoint=c;running()}
        suspend fun read():RemoteImages {running();return transport.images().also{running()}}
        try {
            require(Regex("([0-9A-F]{2}:){5}[0-9A-F]{2}").matches(address)) {"Invalid Bluetooth target address"}
            val meta=requireNotNull(pkg.manifest.migration) {"This release has no shared recovery preparation"}
            val bytes=requireNotNull(pkg.migration)
            require(meta.role=="MIGRATION" && pkg.manifest.legacyRecoverySignedHashes.isNotEmpty())
            checkpoint=store.load(pkg.bundleDigest,address)
            resetRetryAuthorized=allowResetRetry && checkpoint?.phase==BootstrapPhase.RESET_INTENT
            require(checkpoint==null || matches(pkg,address,checkpoint!!)) {"Bootstrap session mismatch"}
            while(true) {
                try {
                    running();transport.connect(address);running();var remote=read()
                    if(remote.recovery.hash==pkg.manifest.targetRecoverySignedHash) {
                        require(remote.recovery.active && remote.recovery.bootable) {"Target recovery not active"}
                        val identity=RuntimeIdentityLookup.forRelease(transport,pkg.manifest);running()
                        require(checkpoint?.observedUid==null || checkpoint?.observedUid==identity.uid) {"Previously verified bootstrap UID changed"}
                        require(checkpoint?.observedIdentity==null || checkpoint?.observedIdentity==identity) {"Previously verified bootstrap loader/anchor identity changed"}
                        validateIdentity(identity)
                        val bound=pkg.bind(identity,address)
                        require(UpdatePlanner.next(bound,remote,null)!=Decision.Reject) {"Unexpected images after recovery preparation"}
                        save(BootstrapCheckpoint(pkg.bundleDigest,address,BootstrapPhase.BOUND,observedUid=identity.uid,observedIdentity=identity.takeIf{pkg.manifest.schemaVersion==3}))
                        running();onBound(identity);running();return
                    }
                    require(eligible(pkg,address,remote,checkpoint)) {"Legacy recovery or source image is not authorized for this shared preparation"}
                    if(checkpoint?.phase==BootstrapPhase.RESET_INTENT && remote.primary?.hash!=meta.signedRegionSha256) {
                        onEvent(UpdateEvent.Paused("Recovery restart state changed unexpectedly; no upload or restart repeated"));return
                    }
                    if(remote.primary?.hash!=meta.signedRegionSha256) {
                        onEvent(UpdateEvent.Planned(Decision.UploadMigration));running()
                        save(BootstrapCheckpoint(pkg.bundleDigest,address,BootstrapPhase.UPLOAD_MIGRATION))
                        transport.upload(bytes){offset->running();require(offset in 0..bytes.size);save(BootstrapCheckpoint(pkg.bundleDigest,address,BootstrapPhase.UPLOAD_MIGRATION,ackOffset=offset));onEvent(UpdateEvent.Progress(Phase.UPLOAD_MIGRATION,offset,bytes.size))}
                        running();val verified=read()
                        require(verified.recovery==remote.recovery && verified.primary?.hash==meta.signedRegionSha256 && verified.primary.bootable) {"Shared preparation upload verification failed"}
                        remote=verified
                    }
                    val beforeReset=read()
                    require(beforeReset==remote && eligible(pkg,address,beforeReset,checkpoint)) {"Images changed before shared preparation restart"}
                    if(checkpoint?.phase==BootstrapPhase.RESET_INTENT && (!resetRetryAuthorized || resetRetryUsed)) {
                        onEvent(UpdateEvent.Paused("Recovery restart already requested. Wait, then choose Prepare again to read its state. A second restart requires explicit confirmation."));return
                    }
                    if(checkpoint?.phase==BootstrapPhase.RESET_INTENT)resetRetryUsed=true
                    save(BootstrapCheckpoint(pkg.bundleDigest,address,BootstrapPhase.RESET_INTENT))
                    onEvent(UpdateEvent.Planned(Decision.RunMigration));running()
                    val ack=MigrationBoot.request(transport,meta.signedRegionSha256,beforeReset.recovery.hash,pkg.manifest.legacyRecoverySignedHashes);running()
                    save(BootstrapCheckpoint(pkg.bundleDigest,address,BootstrapPhase.RESET_INTENT,resetAcknowledged=ack==ResetAck.ACKNOWLEDGED))
                    running();wait(2_000);running()
                } catch(e:TransportDisconnected) {
                    if(retries>=3){onEvent(UpdateEvent.Paused("Recovery preparation reconnect limit reached; choose Prepare again to read the state"));return}
                    val pause=listOf(2_000L,5_000L,10_000L)[retries++]
                    onEvent(UpdateEvent.Reconnecting(retries,pause));running();wait(pause)
                }
            }
        } catch(_:Stopped){onEvent(UpdateEvent.Stopped)}
        catch(e:CancellationException){throw e}
        catch(e:Exception){onEvent(UpdateEvent.Paused(e.message ?: e.javaClass.simpleName))}
        finally {try{withContext(NonCancellable){try{transport.close()}catch(_:Exception){}}}finally{mutex.unlock()}}
    }
}
