package org.openvimar.updater

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import org.openvimar.updater.core.*
import java.io.File
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec

class FleetBleExecutorTest {
    private class Harness {
        val common=CommonPackageValidator.validate(CommonPackageReader.read(File("../test-fixtures/synthetic-common.zip").inputStream()),
            KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(File("../test-fixtures/synthetic-common-public.der").readBytes())),"9.0.0")
        val identity=RuntimeIdentity(1,"VIMAR30805",2,listOf("11223344","55667788"),common.manifest.allowedLoaderSha256.first())
        var observed=identity;var unavailable=false;var writes=0;var closes=0;var reset=ResetAck.ACKNOWLEDGED
        var checkpoint:Checkpoint?=null
        var primary=common.manifest.allowedSourceSignedHashes.first()
        val store=object:SessionStore {
            override suspend fun load(bundleDigest:String,address:String)=checkpoint
            override suspend fun load(bundleDigest:String,address:String,targetUid:List<String>?)=checkpoint
            override suspend fun save(checkpoint:Checkpoint){this@Harness.checkpoint=checkpoint}
        }
        val transport=object:BleTransport {
            override suspend fun connect(address:String){}
            override suspend fun identity():RuntimeIdentity {if(unavailable)throw IdentityCommandUnavailable();return observed}
            override suspend fun images()=RemoteImages(RemoteImage(primary,false,true),RemoteImage(common.manifest.targetRecoverySignedHash,true,true))
            override suspend fun upload(data:ByteArray,onAck:suspend(Int)->Unit){writes++;onAck(data.size);primary=common.manifest.main.signedRegionSha256}
            override suspend fun reset():ResetAck{writes++;return reset}
            override suspend fun close(){closes++}
        }
        val device=DeviceRecord("selected","Desk",address="AA:BB:CC:DD:EE:FF",uid=identity.uid)
        val ref=FleetReleaseRef(common.bundleDigest,common.manifest.main.version,common.manifest.main.signedRegionSha256,"/private/cache.zip")
        fun context(uid:List<String> = identity.uid)=FleetExecutionContext("group",FleetJob("job",device.copy(uid=uid),FleetRoute.BLE,nearbyReady=true),ref)
        val executor=FleetBleExecutor({common},{transport},store)
    }
    @Test fun actualCoordinatorVerifiesUploadAndKeepsOnlineReturnSeparate()=runBlocking {
        val h=Harness();val result=h.executor.execute(h.context()){}
        assertEquals(FleetJobState.AWAITING_RETURN,result.state);assertEquals(2,h.writes)
        assertEquals(Phase.AWAIT_OPERATOR,h.checkpoint!!.phase);assertTrue(h.checkpoint!!.resetAcknowledged)
        assertTrue(h.closes>=1)
    }
    @Test fun plannedUidMismatchAndMissingLegacyCommandNeverWrite()=runBlocking {
        val h=Harness()
        assertEquals(FleetJobState.BLOCKED,h.executor.execute(h.context(listOf("99999999","88888888"))){}.state)
        h.unavailable=true;assertEquals(FleetJobState.BLOCKED,h.executor.execute(h.context()){}.state)
        assertEquals(0,h.writes)
    }
    @Test fun uncertainResetCheckpointIsNeverAutomaticallyRetried()=runBlocking {
        val h=Harness();h.checkpoint=Checkpoint(bundleDigest=h.common.bundleDigest,bleAddress=h.device.address!!,phase=Phase.FINAL_RESET_INTENT,targetUid=h.identity.uid)
        assertEquals(FleetJobState.UNCERTAIN_RESET,h.executor.execute(h.context()){}.state);assertEquals(0,h.writes)
    }
    @Test fun runtimeIdentityIsCheckedAgainAtMutationBoundary()=runBlocking {
        val h=Harness();var events=0
        val result=h.executor.execute(h.context()){if(++events==1)h.observed=h.identity.copy(uid=listOf("99999999","88888888"))}
        assertTrue(result.state in setOf(FleetJobState.BLOCKED,FleetJobState.PAUSED));assertEquals(0,h.writes)
    }
    @Test fun nearbyAndImmutableReleaseReferenceAreRequired()=runBlocking {
        val h=Harness();val c=h.context()
        assertEquals(FleetJobState.BLOCKED,h.executor.execute(c.copy(job=c.job.copy(nearbyReady=false))){}.state)
        assertEquals(FleetJobState.BLOCKED,h.executor.execute(c.copy(release=c.release.copy(digest="f".repeat(64)))){}.state)
        assertEquals(0,h.writes)
    }
}
