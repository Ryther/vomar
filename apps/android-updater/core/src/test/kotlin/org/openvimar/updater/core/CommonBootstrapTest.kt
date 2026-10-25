package org.openvimar.updater.core

import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec

class CommonBootstrapTest {
    private val address="AA:BB:CC:DD:EE:FF"
    private fun common():ValidatedCommonPackage {
        val fixture=File("../test-fixtures")
        val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(File(fixture,"synthetic-common-public.der").readBytes()))
        val main=CommonPackageValidator.validate(CommonPackageReader.read(File(fixture,"synthetic-common.zip").inputStream()),key,"0.3.0")
        return main.copy(manifest=main.manifest.copy(legacyRecoverySignedHashes=listOf("d".repeat(64)),
            migration=main.manifest.main.copy(file="migration.signed.bin",role="MIGRATION",signedRegionSha256="e".repeat(64))),migration=byteArrayOf(9,8,7))
    }
    private class Store(var checkpoint:BootstrapCheckpoint?=null):BootstrapStore {
        val saved=mutableListOf<BootstrapCheckpoint>()
        override suspend fun load(digest:String,address:String)=checkpoint
        override suspend fun save(checkpoint:BootstrapCheckpoint){this.checkpoint=checkpoint;saved+=checkpoint}
    }
    private class Transport(val pkg:ValidatedCommonPackage):BleTransport,MigrationBootTransport {
        var remote=RemoteImages(RemoteImage("c".repeat(64),false,true),RemoteImage("d".repeat(64),true,true))
        var runtime=RuntimeIdentity(1,"VIMAR30805",2,listOf("11223344","55667788"),"a".repeat(64))
        val uploaded=mutableListOf<ByteArray>();var resets=0;var queries=0;var closes=0;var install=true;var purposeAvailable=false;var purposeBoots=0
        var beforeReset:()->Unit={};var afterUpload:()->Unit={}
        override suspend fun connect(address:String){}
        override suspend fun identity():RuntimeIdentity {queries++;if(remote.recovery.hash!=pkg.manifest.targetRecoverySignedHash)throw IdentityCommandUnavailable();return runtime}
        override suspend fun bootMigration(expectedHash:String):ResetAck {
            if(!purposeAvailable)throw MigrationBootCommandUnavailable()
            assertEquals(pkg.manifest.migration!!.signedRegionSha256,expectedHash);beforeReset();purposeBoots++
            if(install)remote=remote.copy(recovery=RemoteImage(pkg.manifest.targetRecoverySignedHash,true,true))
            return ResetAck.ACKNOWLEDGED
        }
        override suspend fun images()=remote
        override suspend fun upload(data:ByteArray,onAck:suspend(Int)->Unit){uploaded+=data;onAck(data.size);remote=remote.copy(primary=RemoteImage(pkg.manifest.migration!!.signedRegionSha256,false,true));afterUpload()}
        override suspend fun reset():ResetAck {beforeReset();resets++;if(install)remote=remote.copy(recovery=RemoteImage(pkg.manifest.targetRecoverySignedHash,true,true));return ResetAck.LOST}
        override suspend fun close(){closes++}
    }
    @Test fun legacyBridgeUploadsOnlySharedMigrationThenReadsIdentityBeforeNormalBinding()=runBlocking {
        val common=common();val transport=Transport(common);val store=Store();var bound:RuntimeIdentity?=null
        transport.beforeReset={assertEquals(BootstrapPhase.RESET_INTENT,store.checkpoint!!.phase)}
        CommonBootstrapCoordinator(wait={}).run(common,address,transport,store,{bound=it}){}
        assertEquals(1,transport.uploaded.size);assertArrayEquals(common.migration,transport.uploaded.single())
        assertEquals(1,transport.resets);assertEquals(2,transport.queries);assertEquals(transport.runtime,bound)
        assertEquals(transport.runtime.uid,store.checkpoint!!.observedUid);assertEquals(BootstrapPhase.BOUND,store.checkpoint!!.phase)
        assertEquals(1,transport.closes)
    }
    @Test fun purposeCapableRecoveryUsesOnlyTheExplicitMigrationCommand()=runBlocking {
        val common=common();val transport=Transport(common).apply{purposeAvailable=true};val store=Store()
        transport.beforeReset={assertEquals(BootstrapPhase.RESET_INTENT,store.checkpoint!!.phase)}
        CommonBootstrapCoordinator(wait={}).run(common,address,transport,store,{}){}
        assertEquals(1,transport.purposeBoots);assertEquals(0,transport.resets)
        assertEquals(BootstrapPhase.BOUND,store.checkpoint!!.phase)
    }
    @Test fun unknownRecoveryOrPrimaryCannotAuthorizeLegacyWrites()=runBlocking {
        for(wrongRecovery in listOf(true,false)) {
            val common=common();val transport=Transport(common)
            transport.remote=if(wrongRecovery)transport.remote.copy(recovery=RemoteImage("f".repeat(64),true,true)) else transport.remote.copy(primary=RemoteImage("f".repeat(64),false,true))
            val events=mutableListOf<UpdateEvent>()
            CommonBootstrapCoordinator(wait={}).run(common,address,transport,Store(),{fail("No identity adoption")}){events+=it}
            assertTrue(transport.uploaded.isEmpty());assertEquals(0,transport.resets);assertTrue(events.last() is UpdateEvent.Paused)
        }
    }
    @Test fun alreadyUploadedHelperNeedsMatchingBootstrapCheckpoint()=runBlocking {
        val common=common();val transport=Transport(common)
        transport.remote=transport.remote.copy(primary=RemoteImage(common.manifest.migration!!.signedRegionSha256,false,true))
        CommonBootstrapCoordinator(wait={}).run(common,address,transport,Store(),{fail("No adoption")}){}
        assertEquals(0,transport.resets);assertTrue(transport.uploaded.isEmpty())
    }
    @Test fun uncertainResetNeverAutomaticallyRetriesIt()=runBlocking {
        val common=common();val transport=Transport(common);transport.install=false
        val store=Store();val events=mutableListOf<UpdateEvent>()
        CommonBootstrapCoordinator(wait={}).run(common,address,transport,store,{fail("No recovery adoption")}){events+=it}
        assertEquals(1,transport.resets);assertEquals(BootstrapPhase.RESET_INTENT,store.checkpoint!!.phase)
        CommonBootstrapCoordinator(wait={}).run(common,address,transport,store,{fail("No recovery adoption")}){}
        assertEquals(1,transport.resets)
    }
    @Test fun previouslyObservedUidCannotBeAdoptedAsAnotherUnit()=runBlocking {
        val common=common();val transport=Transport(common);transport.remote=transport.remote.copy(recovery=RemoteImage(common.manifest.targetRecoverySignedHash,true,true))
        val store=Store(BootstrapCheckpoint(common.bundleDigest,address,BootstrapPhase.BOUND,observedUid=listOf("deadbeef","01020304")))
        val events=mutableListOf<UpdateEvent>()
        CommonBootstrapCoordinator(wait={}).run(common,address,transport,store,{fail("UID changed")}){events+=it}
        assertTrue(events.last() is UpdateEvent.Paused);assertEquals(0,transport.resets);assertTrue(transport.uploaded.isEmpty())
    }
    @Test fun mainOnlyReleaseNeverAuthorizesTheBridge()=runBlocking {
        val common=common().copy(manifest=common().manifest.copy(migration=null,legacyRecoverySignedHashes=emptyList()),migration=null)
        val transport=Transport(common);val events=mutableListOf<UpdateEvent>()
        CommonBootstrapCoordinator(wait={}).run(common,address,transport,Store(),{fail("No adoption")}){events+=it}
        assertTrue(events.last() is UpdateEvent.Paused);assertTrue(transport.uploaded.isEmpty());assertEquals(0,transport.resets)
    }
    @Test fun freshRunCannotSpendRetryAuthorityOnItsOwnUncertainRestart()=runBlocking {
        val common=common();val transport=Transport(common);transport.install=false
        CommonBootstrapCoordinator(wait={}).run(common,address,transport,Store(),{},allowResetRetry=true){}
        assertEquals(1,transport.resets)
    }
    @Test fun explicitlyConfirmedPreviousRestartIsRetriedOnlyOnce()=runBlocking {
        val common=common();val transport=Transport(common);transport.install=false
        transport.remote=transport.remote.copy(primary=RemoteImage(common.manifest.migration!!.signedRegionSha256,false,true))
        val store=Store(BootstrapCheckpoint(common.bundleDigest,address,BootstrapPhase.RESET_INTENT))
        CommonBootstrapCoordinator(wait={}).run(common,address,transport,store,{},allowResetRetry=true){}
        assertEquals(1,transport.resets);assertTrue(transport.uploaded.isEmpty())
    }
    @Test fun stopAfterHelperUploadPreventsRestartAndIdentityAdoption()=runBlocking {
        val common=common();val transport=Transport(common);val coordinator=CommonBootstrapCoordinator(wait={})
        transport.afterUpload={coordinator.stop()};val events=mutableListOf<UpdateEvent>()
        coordinator.run(common,address,transport,Store(),{fail("Stopped")}){events+=it}
        assertEquals(0,transport.resets);assertTrue(events.last() is UpdateEvent.Stopped)
    }

}
