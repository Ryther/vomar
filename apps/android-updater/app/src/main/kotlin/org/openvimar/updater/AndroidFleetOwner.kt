package org.openvimar.updater

import android.content.Context
import kotlinx.coroutines.*
import org.openvimar.updater.ble.NordicBleTransport
import java.io.File
import org.openvimar.updater.core.*

internal data class FleetBleReadback(val checkpoint:Checkpoint,val remote:RemoteImages,val targetRecoveryHash:String)

internal class FleetRuntime internal constructor(val records:FleetStore,val releases:AndroidFleetReleases,
    scope:CoroutineScope,persistence:FleetQueuePersistence,private val ble:FleetJobExecutor,
    private val inspect:suspend(DeviceRecord)->DeviceRecord,
    private val selectBle:suspend(FleetExecutionContext)->Unit,
    private val refreshBle:suspend(FleetExecutionContext)->FleetBleReadback) {
    @Volatile private var zigbee:FleetJobExecutor?=null
    val queue=FleetQueue(scope,persistence,FleetJobExecutor{context,emit->
        if(context.job.route==FleetRoute.BLE)ble.execute(context,emit)
        else zigbee?.execute(context,emit) ?: FleetExecutionResult(FleetJobState.BLOCKED,"Configure and connect this Zigbee network before updating")
    })
    fun setZigbeeExecutor(executor:FleetJobExecutor){zigbee=executor}
    suspend fun inspectDevice(record:DeviceRecord,persist:Boolean=true):DeviceRecord {
        val observed=inspect(record)
        if(persist)withContext(Dispatchers.Main.immediate){records.upsert(observed)}
        return observed
    }
    suspend fun selectBleSession(jobId:String) {
        val group=queue.groups.value.firstOrNull{g->g.jobs.any{it.id==jobId}} ?: error("Unknown group job")
        val job=group.jobs.first{it.id==jobId};require(job.route==FleetRoute.BLE)
        selectBle(FleetExecutionContext(group.id,job,group.release))
    }
    suspend fun refreshBleEvidence(jobId:String) {
        val group=queue.groups.value.firstOrNull{g->g.jobs.any{it.id==jobId}} ?: error("Unknown group job")
        val job=group.jobs.first{it.id==jobId};require(job.route==FleetRoute.BLE)
        val evidence=refreshBle(FleetExecutionContext(group.id,job,group.release))
        queue.recordBleReadback(jobId,evidence.checkpoint,evidence.remote,evidence.targetRecoveryHash)
    }
}

/** One application owner. Construction restores metadata but never starts work. */
internal object AndroidFleetOwner {
    private var owner:FleetRuntime?=null
    @Synchronized fun get(context:Context,zigbeeExecutor:FleetJobExecutor?=null):FleetRuntime {
        owner?.let{runtime->zigbeeExecutor?.let(runtime::setZigbeeExecutor);return runtime}
        val app=context.applicationContext
        val releases=AndroidFleetReleases(app);val controller=AndroidSessionOwner.get(app)
        val ble=FleetJobExecutor{job,emit->controller.executeFleet{check->
            FleetBleExecutor(releases::load,{address->NordicBleTransport(app,address)},AndroidSessionStore(app.filesDir),check).execute(job,emit)
        }}
        return FleetRuntime(FleetStore(app),releases,CoroutineScope(SupervisorJob()+Dispatchers.IO),
            FileFleetQueuePersistence(File(app.filesDir,"fleet-queue.bin")),ble,{record->controller.executeFleet{check->
                FleetDeviceInspector({address->NordicBleTransport(app,address)}).inspect(record,check)
            }},{job->controller.executeFleet{check->
                val common=releases.load(job.release);val record=job.job.device;val address=requireNotNull(record.address)
                val transport=NordicBleTransport(app,address)
                try {
                    check();transport.connect(address);check();val identity=RuntimeIdentityLookup.forRelease(transport,common.manifest)
                    require(identity.uid==record.uid){"Runtime UID differs from this group job"}
                    val bound=common.bind(identity,address)
                    val remote=org.openvimar.updater.core.IdentityBoundTransport(transport,identity,common.manifest).images()
                    val checkpoint=AndroidSessionStore(app.filesDir).load(bound.bundleDigest,address,bound.targetUid)
                    require(org.openvimar.updater.core.UpdatePlanner.next(bound,remote,checkpoint)!=org.openvimar.updater.core.Decision.Reject){"Runtime images do not match this job's verified release"}
                    val documents=DocumentRepository(app)
                    documents.importAnyStream(File(job.release.cachePath).inputStream(),check){commit->check();commit()}
                    documents.bindCommonTarget(address,identity,check){commit->check();commit()}
                } finally {withContext(NonCancellable){transport.close()}}
            }},{job->controller.executeFleet{check->
                val common=releases.load(job.release);val record=job.job.device;val address=requireNotNull(record.address)
                val transport=NordicBleTransport(app,address)
                try {
                    check();transport.connect(address);check();val identity=RuntimeIdentityLookup.forRelease(transport,common.manifest)
                    require(identity.uid==record.uid){"Runtime UID differs from this group job"}
                    val bound=common.bind(identity,address)
                    val remote=IdentityBoundTransport(transport,identity,common.manifest).images();check()
                    val checkpoint=requireNotNull(AndroidSessionStore(app.filesDir).load(bound.bundleDigest,address,bound.targetUid)){"No matching engine checkpoint is available"}
                    require(UpdatePlanner.matches(bound,checkpoint)){"Checkpoint identity mismatch"}
                    FleetBleReadback(checkpoint,remote,common.manifest.targetRecoverySignedHash)
                } finally {withContext(NonCancellable){transport.close()}}
            }}).also{runtime->
                zigbeeExecutor?.let(runtime::setZigbeeExecutor);owner=runtime
            }
    }
}
