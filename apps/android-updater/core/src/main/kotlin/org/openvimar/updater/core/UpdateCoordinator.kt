package org.openvimar.updater.core

import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex

/** One explicitly initiated run. Never starts itself on process restoration. */
class UpdateCoordinator(private val wait:suspend(Long)->Unit={delay(it)},private val now:()->Long={System.nanoTime()/1_000_000}) {
    private val mutex=Mutex()
    @Volatile private var stopped=false
    fun stop() { stopped=true }
    private suspend fun checkRunning() { currentCoroutineContext().ensureActive(); if(stopped) throw Stopped() }
    private class Stopped:Exception()
    /** allowResetRetry requires a fresh, explicitly confirmed user Resume action.
     * Authority applies only to the uncertain stage present when this run starts.
     */
    suspend fun run(pkg:ValidatedPackage,underlyingTransport:BleTransport,store:SessionStore,allowResetRetry:Boolean=false,onEvent:suspend(UpdateEvent)->Unit) {
        val transport=if(pkg.runtimeIdentity!=null) IdentityBoundTransport(underlyingTransport,pkg.runtimeIdentity,requireNotNull(pkg.commonManifest)) else underlyingTransport
        check(mutex.tryLock()) { "An update is already running" }
        stopped=false
        var checkpoint:Checkpoint?=null
        var retries=0
        var migrationDeadline:Long?=null
        var authorizedRetryPhase:Phase?=null
        var resetRetryConsumed=false
        fun mayRetry(phase:Phase)=allowResetRetry && authorizedRetryPhase==phase && !resetRetryConsumed
        fun decision(remote:RemoteImages):Decision {
            val planned=UpdatePlanner.next(pkg,remote,checkpoint)
            return if(planned==Decision.AwaitOperator && mayRetry(Phase.FINAL_RESET_INTENT)) Decision.ReturnToMain else planned
        }
        suspend fun save(c:Checkpoint) { checkRunning(); store.save(c); checkpoint=c; checkRunning() }
        suspend fun read():RemoteImages { checkRunning(); return transport.images().also { checkRunning() } }
        fun record(phase:Phase)=Checkpoint(bundleDigest=pkg.bundleDigest,bleAddress=pkg.manifest.device.bleAddress,phase=phase,targetUid=pkg.targetUid,runtimeIdentity=pkg.checkpointIdentity)
        try {
            checkRunning()
            checkpoint=store.load(pkg.bundleDigest,pkg.manifest.device.bleAddress,pkg.targetUid)
            require(checkpoint==null || UpdatePlanner.matches(pkg,checkpoint)) { "Session identity/schema mismatch" }
            authorizedRetryPhase=when {
                checkpoint?.phase==Phase.MIGRATION_RESET_INTENT -> Phase.MIGRATION_RESET_INTENT
                checkpoint?.phase in listOf(Phase.FINAL_RESET_INTENT,Phase.AWAIT_OPERATOR) && checkpoint?.resetAcknowledged==false -> Phase.FINAL_RESET_INTENT
                else -> null
            }
            while(true) {
                try {
                    checkRunning(); transport.connect(pkg.manifest.device.bleAddress); checkRunning()
                    var remote=read()
                    while(true) {
                        checkRunning()
                        val decision=decision(remote)
                        onEvent(UpdateEvent.Planned(decision)); checkRunning()
                        when(decision) {
                            Decision.Reject -> error("Unexpected recovery or primary image")
                            Decision.AwaitOperator -> { onEvent(UpdateEvent.AwaitingOperator(checkpoint?.resetAcknowledged==true)); return }
                            Decision.UploadMigration,Decision.UploadMain -> {
                                val migration=decision==Decision.UploadMigration
                                val bytes=if(migration) pkg.migration else pkg.main
                                val phase=if(migration) Phase.UPLOAD_MIGRATION else Phase.UPLOAD_MAIN
                                save(record(phase))
                                checkRunning()
                                transport.upload(bytes) { offset ->
                                    checkRunning(); require(offset in 0..bytes.size) { "Invalid remote offset" }
                                    save(record(phase).copy(ackOffset=offset))
                                    onEvent(UpdateEvent.Progress(phase,offset,bytes.size)); checkRunning()
                                }
                                checkRunning()
                                val verified=read()
                                val expected=if(migration) pkg.manifest.migration.signedRegionSha256 else pkg.manifest.main.signedRegionSha256
                                require(verified.primary?.hash==expected && verified.primary.bootable && verified.recovery==remote.recovery) { "Upload verification failed" }
                                remote=verified
                            }
                            Decision.RunMigration,Decision.ReturnToMain -> {
                                val migration=decision==Decision.RunMigration
                                // Readback immediately before each reset; progress alone never grants authority.
                                remote=read()
                                require(decision(remote)==decision) { "Images changed before reset" }
                                if(migration && checkpoint?.phase==Phase.MIGRATION_RESET_INTENT && !mayRetry(Phase.MIGRATION_RESET_INTENT)) {
                                    val deadline=migrationDeadline ?: (now()+120_000).also { migrationDeadline=it }
                                    if(now()>=deadline) { onEvent(UpdateEvent.Paused("Migration reconnect window expired")); return }
                                    checkRunning(); wait(minOf(2_000,deadline-now())); remote=read(); continue
                                }
                                val phase=if(migration) Phase.MIGRATION_RESET_INTENT else Phase.FINAL_RESET_INTENT
                                // Consume before save/reset: disconnect or old readback cannot grant a second retry.
                                if(mayRetry(phase)) resetRetryConsumed=true
                                save(record(phase)); checkRunning()
                                val ack=if(migration&&pkg.commonManifest!=null)MigrationBoot.request(transport,
                                    pkg.manifest.migration.signedRegionSha256,remote.recovery.hash,emptyList()) else transport.reset(); checkRunning()
                                save(record(phase).copy(resetAcknowledged=ack==ResetAck.ACKNOWLEDGED))
                                if(!migration) {
                                    if(ack==ResetAck.LOST) {
                                        checkRunning(); transport.connect(pkg.manifest.device.bleAddress)
                                        require(UpdatePlanner.next(pkg,read(),checkpoint)==Decision.AwaitOperator) { "Unexpected images after final reset" }
                                    }
                                    save(checkpoint!!.copy(phase=Phase.AWAIT_OPERATOR))
                                    onEvent(UpdateEvent.AwaitingOperator(ack==ResetAck.ACKNOWLEDGED)); return
                                }
                                migrationDeadline=now()+120_000
                                checkRunning(); wait(2_000); checkRunning(); transport.connect(pkg.manifest.device.bleAddress); remote=read()
                            }
                        }
                    }
                } catch(e:TransportDisconnected) {
                    if(retries>=3) { onEvent(UpdateEvent.Paused("Reconnect limit reached")); return }
                    val backoff=listOf(2_000L,5_000L,10_000L)[retries++]
                    onEvent(UpdateEvent.Reconnecting(retries,backoff)); checkRunning(); wait(backoff)
                }
            }
        } catch(e:Stopped) { onEvent(UpdateEvent.Stopped) }
        catch(e:CancellationException) { throw e }
        catch(e:Exception) { onEvent(UpdateEvent.Paused(e.message ?: e.javaClass.simpleName)) }
        finally {
            try {
                withContext(NonCancellable) { try { transport.close() } catch(_:Exception) { /* Preserve the update outcome. */ } }
            } finally { mutex.unlock() }
        }
    }
}
