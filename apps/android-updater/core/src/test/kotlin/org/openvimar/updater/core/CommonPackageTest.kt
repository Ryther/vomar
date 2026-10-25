package org.openvimar.updater.core

import java.io.File
import java.security.KeyFactory
import java.security.KeyPairGenerator
import java.security.Signature
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlinx.serialization.json.*
import java.security.spec.X509EncodedKeySpec
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class CommonPackageTest {
    private val fixture=File("../test-fixtures")
    private fun raw()=CommonPackageReader.read(File(fixture,"synthetic-common.zip").inputStream())
    private fun key()=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(File(fixture,"synthetic-common-public.der").readBytes()))
    private fun common()=CommonPackageValidator.validate(raw(),key(),"0.3.0")
    private fun identity(uid:List<String> = listOf("11223344","55667788"))=RuntimeIdentity(1,"VIMAR30805",2,uid,"a".repeat(64))
    private val address="AA:BB:CC:DD:EE:FF"
    @Test fun validatesPythonSignedCommonFixtureWithoutDeviceEnrollment() {
        val common=common()
        assertEquals(2,common.manifest.schemaVersion)
        assertEquals("MAIN",common.manifest.main.role)
        assertEquals("0.6.0",common.manifest.main.version)
        val first=common.bind(identity(),address)
        val second=common.bind(identity(listOf("deadbeef","01020304")),"AA:BB:CC:DD:EE:00")
        assertEquals(first.bundleDigest,second.bundleDigest)
        assertNotEquals(first.targetUid,second.targetUid)
        assertEquals("",first.manifest.device.ieee)
    }
    @Test fun rejectsTamperedManifestAndImageAndIncompatibleApp() {
        val raw=raw()
        assertThrows(Exception::class.java){CommonPackageValidator.validate(raw.copy(manifest=raw.manifest+32.toByte()),key(),"0.3.0")}
        assertThrows(Exception::class.java){CommonPackageValidator.validate(raw.copy(main=raw.main.copyOf().apply{this[520]=(this[520].toInt() xor 1).toByte()}),key(),"0.3.0")}
        assertThrows(Exception::class.java){CommonPackageValidator.validate(raw,key(),"0.2.9")}
    }
    @Test fun refusesUnknownLoaderWrongModelLayoutAndMalformedUid() {
        val common=common()
        for(identity in listOf(identity().copy(loaderSha256="d".repeat(64)),identity().copy(model="UNKNOWN"),identity().copy(layoutVersion=1),identity().copy(uid=listOf("1","2")))) {
            assertThrows(Exception::class.java){common.bind(identity,address)}
        }
    }
    @Test fun checkpointsCannotBeReusedForAnotherUnitAtTheSameAddress() {
        val first=common().bind(identity(),address)
        val second=common().bind(identity(listOf("deadbeef","01020304")),address)
        val checkpoint=Checkpoint(bundleDigest=first.bundleDigest,bleAddress=address,phase=Phase.UPLOAD_MAIN,targetUid=first.targetUid)
        assertTrue(UpdatePlanner.matches(first,checkpoint))
        assertFalse(UpdatePlanner.matches(second,checkpoint))
        assertFalse(UpdatePlanner.matches(first,checkpoint.copy(targetUid=null)))
    }
    @Test fun mainOnlyCommonReleaseRejectsLegacyRecoveryAndAcceptsTargetRecovery() {
        val pkg=common().bind(identity(),address)
        fun remote(recovery:String)=RemoteImages(RemoteImage("c".repeat(64),true,true),RemoteImage(recovery,true,true))
        assertEquals(Decision.UploadMain,UpdatePlanner.next(pkg,remote("b".repeat(64)),null))
        assertEquals(Decision.Reject,UpdatePlanner.next(pkg,remote("d".repeat(64)),null))
    }
    private class IdentityTransport(var identity:RuntimeIdentity):BleTransport {
        var uploads=0; var resets=0; var connects=0;var queries=0
        override suspend fun connect(address:String){connects++}
        override suspend fun identity():RuntimeIdentity {queries++;return identity}
        override suspend fun images()=RemoteImages(RemoteImage("c".repeat(64),true,true),RemoteImage("b".repeat(64),true,true))
        override suspend fun upload(data:ByteArray,onAck:suspend(Int)->Unit){uploads++}
        override suspend fun reset():ResetAck {resets++;return ResetAck.ACKNOWLEDGED}
        override suspend fun close(){}
    }
    @Test fun changedRuntimeUidPreventsUploadAndReset()=runBlocking {
        val common=common();val expected=identity();val delegate=IdentityTransport(expected)
        val transport=IdentityBoundTransport(delegate,expected,common.manifest)
        transport.connect(address)
        delegate.identity=expected.copy(uid=listOf("deadbeef","01020304"))
        var rejected=0
        try{transport.upload(byteArrayOf(1)) {}}catch(_:IllegalArgumentException){rejected++}
        try{transport.reset()}catch(_:IllegalArgumentException){rejected++}
        assertEquals(2,rejected);assertEquals(0,delegate.uploads);assertEquals(0,delegate.resets)
    }
    @Test fun missingIdentityCommandPausesBeforeAnyUpload()=runBlocking {
        val pkg=common().bind(identity(),address)
        val delegate=object:BleTransport {
            var uploads=0
            override suspend fun connect(address:String){}
            override suspend fun images()=error("must reject missing identity before image reads")
            override suspend fun upload(data:ByteArray,onAck:suspend(Int)->Unit){uploads++}
            override suspend fun reset()=error("must not reset")
            override suspend fun close(){}
        }
        val events=mutableListOf<UpdateEvent>()
        UpdateCoordinator(wait={}).run(pkg,delegate,FakeStore()){events+=it}
        assertEquals(0,delegate.uploads)
        assertTrue(events.last() is UpdateEvent.Paused)
        assertTrue((events.last() as UpdateEvent.Paused).reason.contains("identity",true))
    }
    private fun rewrittenImage(extraPayload:Int=0,mutateUnprotected:(ByteArray)->ByteArray={it},mutate:(ByteArray)->Unit):Pair<RawCommonPackage,java.security.PublicKey> {
        val raw=raw();val pair=KeyPairGenerator.getInstance("EC").apply{initialize(256)}.generateKeyPair()
        val b=ByteBuffer.wrap(raw.main).order(ByteOrder.LITTLE_ENDIAN)
        val end=(b.getShort(8).toInt() and 65535)+b.getInt(12)+(b.getShort(10).toInt() and 65535)
        val protectedStart=512+b.getInt(12)
        val region=(raw.main.copyOfRange(0,protectedStart)+ByteArray(extraPayload)+raw.main.copyOfRange(protectedStart,end)).apply{
            ByteBuffer.wrap(this).order(ByteOrder.LITTLE_ENDIAN).putInt(12,b.getInt(12)+extraPayload);mutate(this)
        }
        val digest=java.security.MessageDigest.getInstance("SHA-256").digest(region)
        val signature=Signature.getInstance("SHA256withECDSA").apply{initSign(pair.private);update(region)}.sign()
        val tlv=ByteBuffer.allocate(4+36+4+32+4+signature.size).order(ByteOrder.LITTLE_ENDIAN)
        tlv.putShort(0x6907.toShort());tlv.putShort(tlv.capacity().toShort());tlv.putShort(1);tlv.putShort(32);tlv.put(java.security.MessageDigest.getInstance("SHA-256").digest(pair.public.encoded));tlv.putShort(0x10);tlv.putShort(32);tlv.put(digest);tlv.putShort(0x22);tlv.putShort(signature.size.toShort());tlv.put(signature)
        val image=region+mutateUnprotected(tlv.array())
        val tree=Json.parseToJsonElement(raw.manifest.toString(Charsets.UTF_8)).jsonObject.toMutableMap()
        val meta=tree.getValue("main").jsonObject.toMutableMap().apply{put("size",JsonPrimitive(image.size));put("fileSha256",JsonPrimitive(sha256(image)));put("signedRegionSha256",JsonPrimitive(sha256(region)))}
        tree["main"]=JsonObject(meta);tree.remove("bundleId")
        tree["bundleId"]=JsonPrimitive(sha256((PackageValidator.canonical(JsonObject(tree))+"\n").toByteArray()))
        val manifest=(PackageValidator.canonical(JsonObject(tree))+"\n").toByteArray()
        val manifestSignature=Signature.getInstance("SHA256withECDSA").apply{initSign(pair.private);update(manifest)}.sign()
        return raw.copy(manifest=manifest,signature=manifestSignature,main=image) to pair.public
    }
    @Test fun authenticatedRestoreRoleCannotBePresentedAsMain() {
        val (raw,key)=rewrittenImage{region->region[region.lastIndex]=4}
        assertThrows(IllegalArgumentException::class.java){CommonPackageValidator.validate(raw,key,"0.3.0")}
    }
    @Test fun correctlySignedOutOfSlotVectorIsRejected() {
        val (raw,key)=rewrittenImage{region->ByteBuffer.wrap(region).order(ByteOrder.LITTLE_ENDIAN).putInt(516,0xb0201)}
        assertThrows(IllegalArgumentException::class.java){CommonPackageValidator.validate(raw,key,"0.3.0")}
    }
    @Test fun fullFileIntegrityIncludesSignatureTlvs() {
        val (raw,key)=rewrittenImage{}
        CommonPackageValidator.validate(raw,key,"0.3.0")
        val altered=raw.main.copyOf().apply{this[lastIndex]=(this[lastIndex].toInt() xor 1).toByte()}
        // The authenticated-region digest is unchanged; a full-file hash mismatch must still reject.
        assertThrows(IllegalArgumentException::class.java){CommonPackageValidator.validate(raw.copy(main=altered),key,"0.3.0")}
    }

    @Test fun correctSignatureStillRequiresThePinnedKeyHashAndKnownTlvs() {
        for(change in listOf<(ByteArray)->ByteArray>(
            {it.copyOf().apply{this[8]=(this[8].toInt() xor 1).toByte()}},
            {val result=it+byteArrayOf(0x45,0x23,1,0,0);ByteBuffer.wrap(result).order(ByteOrder.LITTLE_ENDIAN).putShort(2,result.size.toShort());result},
            {val result=it.copyOfRange(0,4)+it.copyOfRange(40,it.size);ByteBuffer.wrap(result).order(ByteOrder.LITTLE_ENDIAN).putShort(2,result.size.toShort());result}
        )) {
            val (raw,key)=rewrittenImage(mutateUnprotected=change){}
            assertThrows(IllegalArgumentException::class.java){CommonPackageValidator.validate(raw,key,"0.3.0")}
        }
    }
    @Test fun signedCommonMainCannotConsumeTheStagingTail() {
        val (raw,key)=rewrittenImage(extraPayload=0xa2200-576){}
        assertTrue(raw.main.size>0xa2000 && raw.main.size<0xa4000)
        assertThrows(IllegalArgumentException::class.java){CommonPackageValidator.validate(raw,key,"0.3.0")}
    }

    @Test fun signedUnsupportedHeaderLoadAddressAndReservedFlagsAreRejected() {
        for(offset in listOf(4,28)) {
            val (raw,key)=rewrittenImage{region->ByteBuffer.wrap(region).order(ByteOrder.LITTLE_ENDIAN).putInt(offset,1)}
            assertThrows(IllegalArgumentException::class.java){CommonPackageValidator.validate(raw,key,"0.3.0")}
        }
    }

}
