package org.openvimar.updater

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import org.openvimar.updater.core.*

class FleetQueueTest {
    private class Memory: FleetQueuePersistence {
        var rows=emptyList<FleetGroup>();var fail=false
        override fun load()=rows
        override fun save(groups:List<FleetGroup>){check(!fail){"disk full"};rows=groups}
    }
    private val release=FleetReleaseRef("a".repeat(64),"0.8.0","b".repeat(64),"/private/release.zip",zigbeeOta=ZigbeeOtaReference(0xfff1,0x3085,8,"c".repeat(64),100,"VIMAR30805",2,"https://example.org/main.ota"),targetRecoveryHash="c".repeat(64))
    private fun device(id:String,network:String?=null)=DeviceRecord(id,id,address="AA:BB:CC:DD:EE:FF",
        uid=listOf("12345678",id.padStart(8,'0')),networkId=network,ieee=if(network!=null)"0x$id" else null,
        installedVersion="0.7.0",firmwareKind=FirmwareKind.CUSTOM,capabilities=setOf("zigbee_ota","zigbee_ota_profile2","recovery_sha256:${"c".repeat(64)}"),observedAt=1,observationSource="test fixture")
    private suspend fun await(check:()->Boolean){withTimeout(3000){while(!check())delay(5)}}
    @Test fun parallelNetworksAreIndependentButBluetoothAndEachNetworkAreExclusive()=runBlocking {
        val memory=Memory();val active=linkedSetOf<String>();val gates=mutableMapOf<String,CompletableDeferred<Unit>>()
        val queue=FleetQueue(this,memory,FleetJobExecutor {c,_->
            synchronized(active){active+=c.job.device.id};val gate=CompletableDeferred<Unit>();gates[c.job.device.id]=gate;gate.await()
            synchronized(active){active-=c.job.device.id};FleetExecutionResult(FleetJobState.VERIFIED,"Observed return")
        })
        val devices=listOf(device("1","net-a"),device("2","net-a"),device("3","net-b"),device("4"),device("5"))
        val group=queue.createGroup(devices,release,FleetMode.NETWORK_PARALLEL)
        group.jobs.filter{it.route==FleetRoute.BLE}.forEach{queue.confirmNearby(it.id)}
        queue.start(group.id)
        await{active.size==3};assertEquals(setOf("1","3","4"),active)
        gates.getValue("1").complete(Unit);gates.getValue("4").complete(Unit)
        await{"2" in active&&"5" in active};assertEquals(setOf("2","3","5"),active)
        gates.values.forEach{it.complete(Unit)};await{queue.groups.value.single().jobs.all{it.state==FleetJobState.VERIFIED}}
    }
    @Test fun sequentialGroupsWaitForNearbyAndNeverStartTwoJobs()=runBlocking {
        val starts=mutableListOf<String>();val gate=CompletableDeferred<Unit>()
        val q=FleetQueue(this,Memory(),FleetJobExecutor{c,_->starts+=c.job.id;gate.await();FleetExecutionResult(FleetJobState.AWAITING_RETURN,"Images verified; return unobserved")})
        val g=q.createGroup(listOf(device("1"),device("2")),release,FleetMode.SEQUENTIAL);q.start(g.id)
        delay(30);assertTrue(starts.isEmpty());assertEquals(FleetJobState.WAITING_NEARBY,q.groups.value[0].jobs[0].state)
        q.confirmNearby(g.jobs[0].id);await{starts.size==1};assertEquals(1,starts.size)
        q.pause(g.id);await{q.groups.value[0].jobs[0].state==FleetJobState.PAUSED}
        gate.complete(Unit);delay(20);assertEquals(1,starts.size)
    }
    @Test fun processDeathPausesAndRequiresExplicitResume()=runBlocking {
        val m=Memory();val g=FleetGroup("group",release,listOf(FleetJob("job",device("1"),FleetRoute.BLE,FleetJobState.RUNNING,true)),FleetMode.SEQUENTIAL,1,false)
        m.rows=listOf(g);var ran=false
        val q=FleetQueue(this,m,FleetJobExecutor{_,_->ran=true;FleetExecutionResult(FleetJobState.VERIFIED,"done")})
        assertEquals(FleetJobState.PAUSED,q.groups.value[0].jobs[0].state);delay(20);assertFalse(ran)
        q.start(g.id);delay(20);assertFalse(ran)
        q.resume(g.id);q.confirmNearby("job");await{ran}
    }
    @Test fun cancellationStopsFutureJobsAndRetainsUncertainEvidence()=runBlocking {
        val started=CompletableDeferred<Unit>();var count=0
        val q=FleetQueue(this,Memory(),FleetJobExecutor {_,_->count++;started.complete(Unit)
            try{awaitCancellation()}catch(_:CancellationException){FleetExecutionResult(FleetJobState.UNCERTAIN_RESET,"Reset acknowledgement missing")}
        })
        val g=q.createGroup(listOf(device("1","net"),device("2","net")),release,FleetMode.SEQUENTIAL)
        q.start(g.id);started.await();q.cancel(g.id)
        await{q.groups.value[0].jobs[0].state==FleetJobState.UNCERTAIN_RESET};assertEquals(1,count)
        assertEquals(FleetJobState.CANCELLED,q.groups.value[0].jobs[1].state)
    }
    @Test fun failedDurableIntentCannotSubmitAnOperation()=runBlocking {
        val m=Memory();var ran=false;val q=FleetQueue(this,m,FleetJobExecutor{_,_->ran=true;FleetExecutionResult(FleetJobState.VERIFIED,"done")})
        val g=q.createGroup(listOf(device("1","net")),release,FleetMode.SEQUENTIAL);m.fail=true
        try{q.start(g.id);fail("disk failure accepted")}catch(_:IllegalStateException){}
        delay(20);assertFalse(ran)
    }
    @Test fun cancelledServerUpdateHoldsItsNetworkAcrossGroupsUntilReadOnlyReconciliation()=runBlocking {
        val started=mutableListOf<String>();val first=CompletableDeferred<Unit>();val gates=mutableMapOf<String,CompletableDeferred<Unit>>()
        val q=FleetQueue(this,Memory(),FleetJobExecutor{c,_->started+=c.job.device.id
            if(c.job.device.id=="1"){first.complete(Unit);awaitCancellation()}
            else{val gate=CompletableDeferred<Unit>();gates[c.job.device.id]=gate;gate.await();FleetExecutionResult(FleetJobState.VERIFIED,"Fresh return")}
        })
        val one=q.createGroup(listOf(device("1","net-a")),release,FleetMode.NETWORK_PARALLEL);q.start(one.id);first.await();q.cancel(one.id)
        await{q.groups.value.first().jobs.first().state==FleetJobState.UNCERTAIN_RESET}
        val two=q.createGroup(listOf(device("2","net-a"),device("3","net-b")),release,FleetMode.NETWORK_PARALLEL);q.start(two.id)
        await{"3" in started};assertFalse("2" in started)
        q.resume(one.id);delay(20);assertEquals(1,started.count{it=="1"})
        var checked=0;q.reconcile(one.jobs.single().id,FleetJobReconciler{checked++;FleetExecutionResult(FleetJobState.PAUSED,"Fresh matching device reports idle")})
        delay(20);assertFalse("2" in started);assertEquals(FleetJobState.CANCELLED,q.groups.value[0].jobs.single().state)
        val again=q.createGroup(listOf(device("1","net-a")),release,FleetMode.SEQUENTIAL);assertNotEquals(FleetJobState.BLOCKED,again.jobs.single().state)
        q.resume(two.id);await{"2" in started};assertEquals(1,checked);assertEquals(1,started.count{it=="1"})
        gates.values.forEach{it.complete(Unit)};await{q.groups.value[1].jobs.all{it.state==FleetJobState.VERIFIED}}
    }
    @Test fun duplicatePendingDeviceCannotCreateASecondOpenIntentUnderAnAlias()=runBlocking {
        val q=FleetQueue(this,Memory(),FleetJobExecutor{_,_->error("No work was started")})
        val original=device("1");q.createGroup(listOf(original),release,FleetMode.SEQUENTIAL)
        val duplicate=q.createGroup(listOf(original.copy(id="renamed-record")),release,FleetMode.SEQUENTIAL)
        assertEquals(FleetJobState.BLOCKED,duplicate.jobs.single().state)
        assertTrue(duplicate.jobs.single().message.contains("open",ignoreCase=true))
    }
    @Test fun manualBleEvidenceMustMatchJobCheckpointUidTargetAndRecoveryBeforeOwnerConfirmation()=runBlocking {
        val q=FleetQueue(this,Memory(),FleetJobExecutor{_,_->error("No firmware operation expected")})
        val device=device("1");val g=q.createGroup(listOf(device),release,FleetMode.SEQUENTIAL);val id=g.jobs.single().id
        val cp=Checkpoint(bundleDigest=release.digest,bleAddress=device.address!!,phase=Phase.AWAIT_OPERATOR,resetAcknowledged=true,targetUid=device.uid)
        val remote=RemoteImages(RemoteImage(release.mainHash,false,true),RemoteImage("c".repeat(64),true,true))
        for(bad in listOf(cp.copy(targetUid=listOf("99999999","88888888")),cp.copy(resetAcknowledged=false))) {
            try{q.recordBleReadback(id,bad,remote,"c".repeat(64));fail("Bad checkpoint accepted")}catch(_:IllegalArgumentException){}
        }
        try{q.recordBleReadback(id,cp,remote,"d".repeat(64));fail("Wrong recovery accepted")}catch(_:IllegalArgumentException){}
        q.recordBleReadback(id,cp,remote,"c".repeat(64));assertEquals(FleetJobState.AWAITING_RETURN,q.groups.value.single().jobs.single().state)
        try{q.confirmReturn(id,release.digest,listOf("99999999","88888888"));fail("Wrong owner target accepted")}catch(_:IllegalArgumentException){}
        q.confirmReturn(id,release.digest,device.uid);assertEquals(FleetJobState.VERIFIED,q.groups.value.single().jobs.single().state)
    }
    @Test fun storageFailureDuringExecutionPausesFutureSubmissionsAndReleasesWorkerWithoutFalseRunningState()=runBlocking {
        val m=Memory();val errors=mutableListOf<Throwable>();val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined+CoroutineExceptionHandler{_,e->errors+=e})
        var count=0
        val q=FleetQueue(scope,m,FleetJobExecutor{_,emit->count++;m.fail=true;emit(FleetExecutionEvent(message="Observed progress"));FleetExecutionResult(FleetJobState.VERIFIED,"Must not publish")})
        val g=q.createGroup(listOf(device("1","net"),device("2","net")),release,FleetMode.SEQUENTIAL)
        q.start(g.id);delay(20)
        assertTrue(q.groups.value.single().paused);assertNotEquals(FleetJobState.RUNNING,q.groups.value.single().jobs.first().state)
        assertEquals(1,count);assertTrue(errors.isEmpty());scope.cancel()
    }
    @Test fun readOnlyReconciliationCannotSubmitNextSequentialJobWithoutExplicitResume()=runBlocking {
        var count=0
        val q=FleetQueue(this,Memory(),FleetJobExecutor{_,_->count++;FleetExecutionResult(if(count==1)FleetJobState.UNCERTAIN_RESET else FleetJobState.VERIFIED,"Observed")})
        val g=q.createGroup(listOf(device("1","net"),device("2","net")),release,FleetMode.SEQUENTIAL);q.start(g.id)
        await{q.groups.value[0].jobs[0].state==FleetJobState.UNCERTAIN_RESET}
        q.reconcile(g.jobs[0].id,FleetJobReconciler{FleetExecutionResult(FleetJobState.VERIFIED,"Fresh target return")})
        delay(20);assertEquals(1,count);assertTrue(q.groups.value[0].paused);assertFalse(q.hasActiveWork())
        q.resume(g.id);await{count==2}
    }
    @Test fun cancelBeforeDispatchDrainsLeaseAndAllowsANewBleIntentWithoutEverCallingExecutor()=runBlocking {
        val work=ArrayDeque<Runnable>();val dispatcher=object:CoroutineDispatcher(){override fun dispatch(context:kotlin.coroutines.CoroutineContext,block:Runnable){work.add(block)}}
        val scope=CoroutineScope(SupervisorJob()+dispatcher);var called=0
        val q=FleetQueue(scope,Memory(),FleetJobExecutor{_,_->called++;FleetExecutionResult(FleetJobState.VERIFIED,"Must not execute")})
        val d=device("1");val g=q.createGroup(listOf(d),release,FleetMode.SEQUENTIAL);q.confirmNearby(g.jobs.single().id);q.start(g.id)
        assertTrue(q.hasActiveWork());q.cancel(g.id);assertTrue(q.hasActiveWork())
        while(work.isNotEmpty())work.removeFirst().run()
        assertFalse(q.hasActiveWork());assertEquals(0,called);assertEquals(FleetJobState.CANCELLED,q.groups.value[0].jobs.single().state)
        assertNotEquals(FleetJobState.BLOCKED,q.createGroup(listOf(d),release,FleetMode.SEQUENTIAL).jobs.single().state);scope.cancel()
    }
}
