package org.openvimar.updater.core

import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException
import java.io.File
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec

class MigrationBootTest {
    private val migration="a".repeat(64);private val legacy="b".repeat(64);private val modern="c".repeat(64)
    private class Transport:BleTransport,MigrationBootTransport {
        var explicit=0;var resets=0;var failure:Exception?=null;var submitted:String?=null
        override suspend fun connect(address:String){}
        override suspend fun images():RemoteImages=error("No image query in primitive")
        override suspend fun upload(data:ByteArray,onAck:suspend(Int)->Unit)=error("No upload in primitive")
        override suspend fun bootMigration(expectedHash:String):ResetAck{explicit++;submitted=expectedHash;failure?.let{throw it};return ResetAck.ACKNOWLEDGED}
        override suspend fun reset():ResetAck{resets++;return ResetAck.ACKNOWLEDGED}
        override suspend fun close(){}
    }
    @Test fun explicitCommandCarriesExactMigrationHashAndNeverOrdinaryResetsModernRecovery()=runBlocking {
        val t=Transport();assertEquals(ResetAck.ACKNOWLEDGED,MigrationBoot.request(t,migration,modern,listOf(legacy)))
        assertEquals(migration,t.submitted);assertEquals(1,t.explicit);assertEquals(0,t.resets)
    }
    @Test fun onlyGenuineCommandUnsupportedOnExactLegacyRecoveryMayFallBack()=runBlocking {
        val t=Transport();t.failure=MigrationBootCommandUnavailable()
        assertEquals(ResetAck.ACKNOWLEDGED,MigrationBoot.request(t,migration,legacy,listOf(legacy)));assertEquals(1,t.resets)
        t.resets=0
        try{MigrationBoot.request(t,migration,modern,listOf(legacy));fail("Modern OS reset fallback permitted")}catch(_:IllegalArgumentException){}
        assertEquals(0,t.resets)
    }
    @Test fun TimeoutAuthMalformedAndRefusalNeverGrantFallback()=runBlocking {
        for(error in listOf(IOException("Timeout"),SecurityException("Authentication failed"),IllegalArgumentException("Malformed"),IllegalStateException("Refused"))) {
            val t=Transport();t.failure=error
            try{MigrationBoot.request(t,migration,legacy,listOf(legacy));fail("Non-ENOTSUP fallback")}catch(_:Exception){}
            assertEquals(0,t.resets)
        }
    }
    @Test fun runtimeBoundCommonCoordinatorUsesPurposeBootForMigrationAndOrdinaryResetOnlyForMain()=runBlocking {
        val common=CommonPackageValidator.validate(CommonPackageReader.read(File("../test-fixtures/synthetic-common.zip").inputStream()),
            KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(File("../test-fixtures/synthetic-common-public.der").readBytes())),"9.0.0").let{p->p.copy(
                manifest=p.manifest.copy(legacyRecoverySignedHashes=listOf(legacy),targetRecoverySignedHash="f".repeat(64),migration=p.manifest.main.copy(role="MIGRATION",signedRegionSha256=migration)),migration=byteArrayOf(1,2,3))}
        val identity=RuntimeIdentity(1,"VIMAR30805",2,listOf("11223344","55667788"),common.manifest.allowedLoaderSha256.first())
        val pkg=common.bind(identity,"AA:BB:CC:DD:EE:FF")
        var remote=RemoteImages(RemoteImage(common.manifest.allowedSourceSignedHashes.first(),false,true),RemoteImage(legacy,true,true))
        var purpose=0;var ordinary=0;var uploaded=0;var cp:Checkpoint?=null
        val transport=object:BleTransport,MigrationBootTransport {
            override suspend fun connect(address:String){}
            override suspend fun identity()=identity
            override suspend fun images()=remote
            override suspend fun upload(data:ByteArray,onAck:suspend(Int)->Unit){uploaded++;onAck(data.size)
                remote=remote.copy(primary=RemoteImage(if(uploaded==1)migration else common.manifest.main.signedRegionSha256,false,true))}
            override suspend fun bootMigration(expectedHash:String):ResetAck{assertEquals(migration,expectedHash);assertEquals(Phase.MIGRATION_RESET_INTENT,cp!!.phase);purpose++
                remote=remote.copy(recovery=RemoteImage(common.manifest.targetRecoverySignedHash,true,true));return ResetAck.ACKNOWLEDGED}
            override suspend fun reset():ResetAck{assertEquals(common.manifest.main.signedRegionSha256,remote.primary!!.hash);ordinary++;return ResetAck.ACKNOWLEDGED}
            override suspend fun close(){}
        }
        val store=object:SessionStore {
            override suspend fun load(bundleDigest:String,address:String)=cp
            override suspend fun save(checkpoint:Checkpoint){cp=checkpoint}
        }
        var clock=0L
        UpdateCoordinator(wait={clock+=it},now={clock}).run(pkg,transport,store){}
        assertEquals(1,purpose);assertEquals(1,ordinary);assertEquals(2,uploaded);assertEquals(Phase.AWAIT_OPERATOR,cp!!.phase)
    }
}
