package org.openvimar.updater.core

import java.io.File
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class CommonSchema3Test {
    private val directory=File("../../../tools/android/test-fixtures/common-v3-synthetic")
    private fun common():ValidatedCommonPackage {
        val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(File(directory,"public.der").readBytes()))
        return CommonPackageValidator.validate(CommonPackageReader.read(File(directory,"one-common.zip").inputStream()),key,"0.6.0")
    }
    private fun identity(pkg:ValidatedCommonPackage)=RuntimeIdentity(2,"VIMAR30805",2,listOf("11223344","55667788"),"",
        typedLoader=pkg.manifest.loaderContracts.single{it.kind==LoaderContract.COMMON},anchorSha256="12".repeat(32))
    @Test fun sameSignedZipAuthenticatesFirstInstallButNormalBindingContainsOnlyUpdateRoles() {
        val pkg=common()
        assertEquals(3,pkg.manifest.schemaVersion)
        assertNotNull(pkg.firstInstall)
        assertEquals(0xc000,pkg.firstInstall!!.loader().size)
        val bound=pkg.bind(identity(pkg),"AA:BB:CC:DD:EE:FF")
        assertEquals("MAIN",pkg.manifest.main.role)
        assertArrayEquals(pkg.main,bound.main)
        assertEquals(identity(pkg),bound.runtimeIdentity)
    }
    @Test fun typedFamilyAndAnchorAreRequiredAndCannotBeRenamedFromLegacyHash() {
        val pkg=common();val valid=identity(pkg)
        for(bad in listOf(valid.copy(anchorSha256=null),valid.copy(typedLoader=LoaderContract(LoaderContract.COMMON,"00".repeat(32))),
            valid.copy(typedLoader=LoaderContract("unknown",valid.typedLoader!!.sha256)),valid.copy(loaderSha256=valid.typedLoader!!.sha256))) {
            assertThrows(IllegalArgumentException::class.java){pkg.bind(bad,"AA:BB:CC:DD:EE:FF")}
        }
        val bound=pkg.bind(valid,"AA:BB:CC:DD:EE:FF")
        val old=Checkpoint(bundleDigest=bound.bundleDigest,bleAddress=bound.manifest.device.bleAddress,phase=Phase.UPLOAD_MAIN,targetUid=bound.targetUid)
        assertFalse(UpdatePlanner.matches(bound,old))
        assertTrue(UpdatePlanner.matches(bound,old.copy(runtimeIdentity=valid)))
        assertFalse(UpdatePlanner.matches(bound,old.copy(runtimeIdentity=valid.copy(anchorSha256="34".repeat(32)))))
    }
    private class Radio(var v2:RuntimeIdentity?,val legacy:RuntimeIdentity):BleTransport {
        var reads0=0;var reads1=0;var uploads=0
        override suspend fun connect(address:String){}
        override suspend fun identity():RuntimeIdentity {reads0++;return legacy}
        override suspend fun identityV2():RuntimeIdentity {reads1++;return v2 ?: throw IdentityCommandUnavailable()}
        override suspend fun images()=error("unused")
        override suspend fun upload(data:ByteArray,onAck:suspend(Int)->Unit){uploads++}
        override suspend fun reset()=ResetAck.ACKNOWLEDGED
        override suspend fun close(){}
    }
    @Test fun onlyGenuineUnsupportedAndExplicitLegacyRecordPermitUnpromotedRead0()=runBlocking {
        val pkg=common();val legacyRecord=pkg.manifest.loaderContracts.single{it.kind==LoaderContract.LEGACY}
        val legacy=RuntimeIdentity(1,"VIMAR30805",2,listOf("11223344","55667788"),legacyRecord.sha256)
        val radio=Radio(null,legacy)
        assertEquals(legacy,RuntimeIdentityLookup.forRelease(radio,pkg.manifest))
        assertEquals(1,radio.reads0)
        val commonOnly=pkg.manifest.copy(loaderContracts=pkg.manifest.loaderContracts.filter{it.kind==LoaderContract.COMMON})
        var refused=false
        try{RuntimeIdentityLookup.forRelease(radio,commonOnly)}catch(_:Exception){refused=true}
        assertTrue(refused);assertEquals(1,radio.reads0)
    }
    @Test fun changedAnchorStopsMutationEvenWhenFamilyUidAndAddressMatch()=runBlocking {
        val pkg=common();val valid=identity(pkg);val radio=Radio(valid,valid)
        val transport=IdentityBoundTransport(radio,valid,pkg.manifest)
        transport.connect("AA:BB:CC:DD:EE:FF")
        radio.v2=valid.copy(anchorSha256="34".repeat(32))
        var refused=false;try{transport.upload(byteArrayOf(1)) {}}catch(_:IllegalArgumentException){refused=true}
        assertTrue(refused);assertEquals(0,radio.uploads);assertEquals(0,radio.reads0)
    }
    @Test fun malformedRefusedOrTimedOutRead1NeverCallsLegacyCommand()=runBlocking {
        val pkg=common();val legacyRecord=pkg.manifest.loaderContracts.single{it.kind==LoaderContract.LEGACY}
        val legacy=RuntimeIdentity(1,"VIMAR30805",2,listOf("11223344","55667788"),legacyRecord.sha256)
        for(failure in listOf(IllegalArgumentException("malformed"),IllegalStateException("refused"),java.io.IOException("timeout"))) {
            var reads0=0
            val radio=object:BleTransport {
                override suspend fun connect(address:String){}
                override suspend fun identity():RuntimeIdentity {reads0++;return legacy}
                override suspend fun identityV2():RuntimeIdentity=throw failure
                override suspend fun images()=error("unused")
                override suspend fun upload(data:ByteArray,onAck:suspend(Int)->Unit)=error("unused")
                override suspend fun reset():ResetAck=error("unused")
                override suspend fun close(){}
            }
            var refused=false;try{RuntimeIdentityLookup.forRelease(radio,pkg.manifest)}catch(_:Exception){refused=true}
            assertTrue(refused);assertEquals(0,reads0)
        }
    }
    @Test fun schema3CannotBeValidatedUsingDifferentCallerSuppliedBytesThanItsAuthenticatedOriginalZip() {
        val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(File(directory,"public.der").readBytes()))
        val raw=CommonPackageReader.read(File(directory,"one-common.zip").inputStream())
        assertThrows(IllegalArgumentException::class.java){CommonPackageValidator.validate(raw.copy(main=raw.main.copyOf().apply{this[520]=(this[520].toInt() xor 1).toByte()}),key,"0.6.0")}
        assertThrows(IllegalArgumentException::class.java){CommonPackageValidator.validate(raw.copy(originalZip=null),key,"0.6.0")}
    }
    @Test fun oldCheckpointCodecDoesNotInventTypedEvidence() {
        val json="""{"bundleDigest":"${"a".repeat(64)}","bleAddress":"AA:BB:CC:DD:EE:FF","phase":"UPLOAD_MAIN","targetUid":["11223344","55667788"]}"""
        val old=kotlinx.serialization.json.Json.decodeFromString<Checkpoint>(json)
        assertNull(old.runtimeIdentity)
        val bound=common().let{it.bind(identity(it),"AA:BB:CC:DD:EE:FF")}
        assertFalse(UpdatePlanner.matches(bound,old.copy(bundleDigest=bound.bundleDigest)))
    }
    @Test fun adoptedLegacyBootstrapCheckpointAlsoPinsCompleteSchema3Identity() {
        val pkg=common();val identity=identity(pkg)
        val old=BootstrapCheckpoint(pkg.bundleDigest,"AA:BB:CC:DD:EE:FF",BootstrapPhase.BOUND,observedUid=identity.uid)
        assertFalse(CommonBootstrapCoordinator.matches(pkg,old.address,old))
        assertTrue(CommonBootstrapCoordinator.matches(pkg,old.address,old.copy(observedIdentity=identity)))
        assertFalse(CommonBootstrapCoordinator.matches(pkg,old.address,old.copy(observedIdentity=identity.copy(uid=listOf("deadbeef","01020304")))))
    }
    @Test fun actualNormalCoordinatorStoresTypedEvidenceAndUploadsOnlyMain()=runBlocking {
        val common=common();val identity=identity(common);val bound=common.bind(identity,"AA:BB:CC:DD:EE:FF")
        var primary=common.manifest.allowedSourceSignedHashes.first();var uploads=0;var resets=0;var legacyReads=0;var typedReads=0
        val saved=mutableListOf<Checkpoint>()
        val store=object:SessionStore {
            override suspend fun load(bundleDigest:String,address:String):Checkpoint?=null
            override suspend fun save(checkpoint:Checkpoint){saved+=checkpoint}
        }
        val radio=object:BleTransport {
            override suspend fun connect(address:String){}
            override suspend fun identity():RuntimeIdentity {legacyReads++;error("Schema3 common family cannot query legacy authority")}
            override suspend fun identityV2():RuntimeIdentity {typedReads++;return identity}
            override suspend fun images()=RemoteImages(RemoteImage(primary,false,true),RemoteImage(common.manifest.targetRecoverySignedHash,true,true))
            override suspend fun upload(data:ByteArray,onAck:suspend(Int)->Unit){uploads++;assertArrayEquals(common.main,data);onAck(data.size);primary=common.manifest.main.signedRegionSha256}
            override suspend fun reset():ResetAck {resets++;return ResetAck.ACKNOWLEDGED}
            override suspend fun close(){}
        }
        val events=mutableListOf<UpdateEvent>();UpdateCoordinator(wait={}).run(bound,radio,store){events+=it}
        assertEquals(1,uploads);assertEquals(1,resets);assertEquals(0,legacyReads);assertTrue(typedReads>=5)
        assertTrue(saved.isNotEmpty()&&saved.all{it.runtimeIdentity==identity})
        assertEquals(UpdateEvent.AwaitingOperator(true),events.last())
    }
    @Test fun allElevenSignedEntriesValidateButStockHelpersNeverBecomeNormalMigration() {
        val directory=File("../../../tools/android/test-fixtures/common-v3-all-options")
        val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(File(directory,"public.der").readBytes()))
        val pkg=CommonPackageValidator.validate(CommonPackageReader.read(File(directory,"one-common.zip").inputStream()),key,"0.6.0")
        assertEquals("RESTORE",pkg.manifest.stockRestore!!.role)
        assertEquals("MIGRATION",pkg.manifest.stockBootstrap!!.role)
        assertNotNull(pkg.manifest.zigbeeOta);assertNotNull(pkg.firstInstall)
        val bound=pkg.bind(identity(pkg),"AA:BB:CC:DD:EE:FF")
        assertEquals("migration.signed.bin",bound.manifest.migration.file)
        java.util.zip.ZipFile(File(directory,"one-common.zip")).use{zip->
            assertArrayEquals(zip.getInputStream(zip.getEntry("migration.signed.bin")).readBytes(),bound.migration)
            assertArrayEquals(zip.getInputStream(zip.getEntry("main.signed.bin")).readBytes(),bound.main)
        }
    }
}
