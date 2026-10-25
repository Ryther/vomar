package org.openvimar.updater

import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.UUID
import org.openvimar.updater.core.*

/** Durable intent, bounded resource scheduling, and no restart on construction. */
internal class FleetQueue(private val scope:CoroutineScope,private val persistence:FleetQueuePersistence,
    private val executor:FleetJobExecutor,private val now:()->Long={System.currentTimeMillis()}) {
    private val lock=Any()
    private val active=mutableMapOf<String,Job>()
    private val reconciling=mutableSetOf<String>()
    private val mutableGroups=MutableStateFlow(persistence.load().map{g->g.copy(paused=true,jobs=g.jobs.map{j->
        when(j.state){FleetJobState.RUNNING->j.copy(state=if(j.route==FleetRoute.ZIGBEE)FleetJobState.UNCERTAIN_RESET else FleetJobState.PAUSED,nearbyReady=false,
                message="Interrupted; a remote operation may still be running. Reconcile status before resuming.")
            FleetJobState.QUEUED,FleetJobState.WAITING_NEARBY->j.copy(state=FleetJobState.PAUSED,nearbyReady=false,message="Interrupted; explicit resume and fresh runtime checks required")
            else->j.copy(nearbyReady=false)}
    })})
    val groups=mutableGroups.asStateFlow()
    fun hasActiveWork():Boolean=synchronized(lock){active.isNotEmpty()}
    init {if(mutableGroups.value.isNotEmpty())persistence.save(mutableGroups.value)}
    private val terminal=setOf(FleetJobState.VERIFIED,FleetJobState.BLOCKED,FleetJobState.FAILED,FleetJobState.CANCELLED)
    private fun commit(next:List<FleetGroup>){
        try {persistence.save(next)}catch(failure:Exception){
            // No additional submission is allowed after a lost durable intent.
            // Preserve the last published evidence and cancel/drain workers.
            mutableGroups.value=groups.value.map{it.copy(paused=true)}
            active.values.toList().forEach{it.cancel()}
            throw failure
        }
        mutableGroups.value=next
    }
    fun createGroup(devices:List<DeviceRecord>,release:FleetReleaseRef,mode:FleetMode):FleetGroup=synchronized(lock){
        require(devices.isNotEmpty()&&devices.size<=100&&devices.map{it.id}.distinct().size==devices.size)
        require(Regex("[0-9a-f]{64}").matches(release.digest)&&Regex("[0-9a-f]{64}").matches(release.mainHash))
        val group=FleetGroup(UUID.randomUUID().toString(),release.copy(),devices.map{record->
            val d=record.copy(uid=record.uid.toList(),capabilities=record.capabilities.toSet())
            val route=FleetPolicy.route(d,release)
            val status=FleetPolicy.status(d,release)
            val duplicate=groups.value.flatMap{it.jobs}.any{prior->prior.state !in terminal&&(
                prior.device.id==d.id||d.uid.size==2&&prior.device.uid==d.uid||
                !d.networkId.isNullOrBlank()&&d.networkId==prior.device.networkId&&!d.ieee.isNullOrBlank()&&d.ieee==prior.device.ieee)}
            FleetJob(UUID.randomUUID().toString(),d,route ?: FleetRoute.BLE,
                if(duplicate||route==null||status.eligibility!=Eligibility.UPDATE)FleetJobState.BLOCKED else if(route==FleetRoute.BLE)FleetJobState.WAITING_NEARBY else FleetJobState.QUEUED,
                message=if(duplicate)"This dimmer already has an open activity; resume or resolve that job first" else if(status.eligibility!=Eligibility.UPDATE)status.reason else if(route==null)"No verified route; legacy units require manual preparation" else if(route==FleetRoute.BLE)"Confirm that this phone is near the selected dimmer" else "Queued")
        },mode,now())
        require(groups.value.size<500){"Archive old groups before creating more"}
        commit(groups.value+group);group
    }
    fun start(groupId:String)=synchronized(lock){
        commit(groups.value.map{if(it.id==groupId&&!it.cancelled)it.copy(paused=false) else it});schedule()
    }
    fun resume(groupId:String)=synchronized(lock){
        commit(groups.value.map{g->if(g.id!=groupId||g.cancelled)g else g.copy(paused=false,jobs=g.jobs.map{j->
            if(j.state==FleetJobState.PAUSED)j.copy(state=if(j.route==FleetRoute.BLE)FleetJobState.WAITING_NEARBY else FleetJobState.QUEUED,
                nearbyReady=false,resumeRequested=true,message="Resume requested; runtime checkpoint will be rechecked") else j
        })});schedule()
    }
    /** Uncertain reset never gains an automatic retry from a group action. */
    fun confirmNearby(jobId:String)=synchronized(lock){
        commit(groups.value.map{g->g.copy(jobs=g.jobs.map{j->if(j.id==jobId&&j.route==FleetRoute.BLE&&j.state==FleetJobState.WAITING_NEARBY)
            j.copy(nearbyReady=true,state=FleetJobState.QUEUED,message="Phone nearby; queued") else j})});schedule()
    }
    fun pause(groupId:String)=stop(groupId,false)
    fun cancel(groupId:String)=stop(groupId,true)
    fun confirmReturn(jobId:String,releaseDigest:String,uid:List<String>)=synchronized(lock){
        val group=groups.value.firstOrNull{g->g.release.digest==releaseDigest&&g.jobs.any{it.id==jobId}} ?: error("Return confirmation does not match a job")
        val job=group.jobs.first{it.id==jobId}
        require(job.state==FleetJobState.AWAITING_RETURN&&job.route==FleetRoute.BLE&&job.device.uid==uid&&uid.size==2){"Return confirmation identity/state mismatch"}
        commit(groups.value.map{g->g.copy(jobs=g.jobs.map{j->if(j.id==jobId)j.copy(state=FleetJobState.VERIFIED,message="Operator confirmed this dimmer returned online") else j})});schedule()
    }
    internal fun recordBleReadback(jobId:String,checkpoint:Checkpoint,remote:RemoteImages,targetRecoveryHash:String)=synchronized(lock){
        val group=groups.value.firstOrNull{g->g.jobs.any{it.id==jobId}} ?: error("Unknown job")
        val job=group.jobs.first{it.id==jobId}
        require(job.route==FleetRoute.BLE&&job.state !in terminal&&job.id !in active&&checkpoint.schemaVersion==1&&checkpoint.bundleDigest==group.release.digest&&checkpoint.bleAddress==job.device.address&&checkpoint.targetUid==job.device.uid)
        require(remote.primary?.let{it.hash==group.release.mainHash&&it.bootable}==true&&remote.recovery.hash==targetRecoveryHash&&remote.recovery.active&&remote.recovery.bootable){"Target MAIN/recovery images are not verified"}
        val evidence=SessionEvidence.from(checkpoint)
        require(evidence.imagesVerified&&!evidence.needsResetConfirmation&&checkpoint.resetAcknowledged){"Reset outcome remains uncertain; use the exact device's explicit resume review"}
        commit(groups.value.map{g->g.copy(jobs=g.jobs.map{j->if(j.id==jobId)j.copy(state=FleetJobState.AWAITING_RETURN,message="Exact target MAIN/recovery and reset checkpoint verified; confirm this dimmer returned online") else j})})
    }
    fun pauseAll(){groups.value.filter{!it.paused&&!it.cancelled}.forEach{pause(it.id)}}
    suspend fun reconcile(jobId:String,reconciler:FleetJobReconciler) {
        val context=synchronized(lock){
            val group=groups.value.firstOrNull{g->g.jobs.any{it.id==jobId}} ?: error("Unknown job")
            val job=group.jobs.first{it.id==jobId}
            require(job.route==FleetRoute.ZIGBEE&&job.state in setOf(FleetJobState.UNCERTAIN_RESET,FleetJobState.AWAITING_RETURN)&&reconciling.add(jobId)){"This job is not awaiting network reconciliation"}
            FleetExecutionContext(group.id,job,group.release)
        }
        try {
            val result=reconciler.reconcile(context)
            require(result.state in setOf(FleetJobState.PAUSED,FleetJobState.VERIFIED,FleetJobState.UNCERTAIN_RESET)){"Reconciliation did not provide safe read-only evidence"}
            synchronized(lock){commit(groups.value.map{g->
                val affected=g.id==context.groupId||g.jobs.any{it.route==FleetRoute.ZIGBEE&&it.device.networkId==context.job.device.networkId&&it.state !in terminal}
                g.copy(paused=g.paused||affected,jobs=g.jobs.map{j->if(j.id==jobId)j.copy(
                    state=if(g.cancelled&&result.state==FleetJobState.PAUSED)FleetJobState.CANCELLED else result.state,
                    message=result.message.take(1024),nearbyReady=false) else j})
            })}
        } finally {synchronized(lock){reconciling.remove(jobId)}}
    }
    private fun stop(groupId:String,cancel:Boolean)=synchronized(lock){
        val ids=groups.value.firstOrNull{it.id==groupId}?.jobs?.map{it.id}.orEmpty()
        commit(groups.value.map{g->if(g.id!=groupId)g else g.copy(paused=true,cancelled=cancel,jobs=g.jobs.map{j->
            if(j.state in terminal||j.state==FleetJobState.UNCERTAIN_RESET||j.state==FleetJobState.AWAITING_RETURN||j.id in active)j
            else j.copy(state=if(cancel)FleetJobState.CANCELLED else FleetJobState.PAUSED,nearbyReady=false,message=if(cancel)"Cancelled before submission" else "Paused")
        })});ids.mapNotNull{active[it]}.forEach{it.cancel()}
    }
    private fun schedule() {
        // lock held. Persist RUNNING before creating an executor coroutine.
        for(groupId in groups.value.map{it.id}) {
            val initial=groups.value.first{it.id==groupId}
            if(initial.paused||initial.cancelled)continue
            for(jobId in initial.jobs.map{it.id}) {
                val g=groups.value.first{it.id==groupId};val j=g.jobs.first{it.id==jobId}
                if(j.state!=FleetJobState.QUEUED||j.id in active)continue
                if(j.route==FleetRoute.BLE&&!j.nearbyReady)continue
                val running=groups.value.flatMap{it.jobs}.filter{it.id in active}
                val unresolved=groups.value.flatMap{it.jobs}.filter{it.route==FleetRoute.ZIGBEE&&it.state in setOf(FleetJobState.UNCERTAIN_RESET,FleetJobState.AWAITING_RETURN)}
                if(g.mode==FleetMode.SEQUENTIAL&&g.jobs.takeWhile{it.id!=jobId}.any{it.state!=FleetJobState.VERIFIED})break
                if(running.any{it.device.id==j.device.id || j.route==FleetRoute.BLE&&it.route==FleetRoute.BLE ||
                    j.route==FleetRoute.ZIGBEE&&it.route==FleetRoute.ZIGBEE&&it.device.networkId==j.device.networkId})continue
                if(j.route==FleetRoute.ZIGBEE&&unresolved.any{it.device.networkId==j.device.networkId})continue
                val context=FleetExecutionContext(g.id,j,g.release)
                commit(groups.value.map{row->row.copy(jobs=row.jobs.map{if(it.id==jobId)it.copy(state=FleetJobState.RUNNING,message="Starting runtime checks",progress=null) else it})})
                val entered=java.util.concurrent.atomic.AtomicBoolean(false)
                val task=scope.launch(start=CoroutineStart.LAZY){
                    entered.set(true)
                    val result=try{executor.execute(context){event->synchronized(lock){
                        commit(groups.value.map{row->row.copy(jobs=row.jobs.map{if(it.id==jobId&&it.state==FleetJobState.RUNNING)
                            it.copy(progress=event.progress?.coerceIn(0,100),message=event.message.take(1024),
                                remoteSubmissionMayHaveStarted=it.remoteSubmissionMayHaveStarted||event.submissionMayHaveStarted) else it})})
                    }}}
                    catch(_:CancellationException){FleetExecutionResult(if(j.route==FleetRoute.ZIGBEE)FleetJobState.UNCERTAIN_RESET else FleetJobState.PAUSED,
                        if(j.route==FleetRoute.ZIGBEE)"Server-side update may still be running. This network remains held until a read-only status check proves its outcome." else "Stopped; checkpoints preserved. Resume explicitly.")}
                    catch(e:Exception){
                        val submitted=synchronized(lock){groups.value.flatMap{it.jobs}.first{it.id==jobId}.remoteSubmissionMayHaveStarted}
                        FleetExecutionResult(if(j.route==FleetRoute.ZIGBEE&&submitted)FleetJobState.UNCERTAIN_RESET else FleetJobState.FAILED,e.message ?: "Operation failed")
                    }
                    synchronized(lock){
                        var durable=true
                        try{commit(groups.value.map{row->row.copy(jobs=row.jobs.map{if(it.id==jobId)
                            it.copy(state=if(row.cancelled&&it.route==FleetRoute.BLE&&result.state==FleetJobState.PAUSED)FleetJobState.CANCELLED
                                else if(result.state in setOf(FleetJobState.QUEUED,FleetJobState.RUNNING,FleetJobState.WAITING_NEARBY))FleetJobState.FAILED else result.state,
                                message=result.message.take(1024),nearbyReady=false) else it})})}
                        catch(_:Exception){
                            durable=false
                            // The last on-disk RUNNING row will become paused or
                            // uncertain at process restoration, never resumed.
                            mutableGroups.value=groups.value.map{row->row.copy(paused=true,jobs=row.jobs.map{if(it.id==jobId)
                                it.copy(state=if(it.route==FleetRoute.ZIGBEE)FleetJobState.UNCERTAIN_RESET else FleetJobState.PAUSED,
                                    nearbyReady=false,message="Local queue storage failed; worker stopped and future submissions paused. Recheck the engine/device before resuming.") else it})}
                        }
                        finally{active.remove(jobId)}
                        if(durable)try{schedule()}catch(_:Exception){/* commit already paused all groups and drained workers */}
                    }
                }
                active[jobId]=task
                task.invokeOnCompletion{synchronized(lock){
                    if(active[jobId]===task){
                        // A coroutine cancelled before dispatch never enters its
                        // body/finally. Retain the lease until this callback.
                        val next=groups.value.map{row->row.copy(paused=true,jobs=row.jobs.map{job->if(job.id!=jobId)job else job.copy(
                            state=if(!entered.get())if(row.cancelled)FleetJobState.CANCELLED else FleetJobState.PAUSED else FleetJobState.UNCERTAIN_RESET,
                            nearbyReady=false,message=if(!entered.get())"Stopped before the executor started" else "Worker ended unexpectedly; reconcile its engine/device before retrying")})}
                        try{commit(next)}catch(_:Exception){mutableGroups.value=next}
                        finally{active.remove(jobId)}
                    }
                }}
                task.start()
            }
        }
    }
}
