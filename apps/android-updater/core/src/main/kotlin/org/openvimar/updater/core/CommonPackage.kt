package org.openvimar.updater.core

import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.PublicKey
import java.security.Signature
import java.security.interfaces.ECPublicKey
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.*

@Serializable data class LoaderContract(val kind:String,val sha256:String) {
    companion object {const val COMMON="common-code44k-anchor-v1";const val LEGACY="legacy-full48k-sha256"}
}
@Serializable data class RuntimeIdentity(val protocol:Int,val model:String,val layoutVersion:Int,val uid:List<String>,val loaderSha256:String,
    val typedLoader:LoaderContract?=null,val anchorSha256:String?=null)
@Serializable data class CommonImage(val file:String,val size:Int,val version:String,val wireVersion:List<Long>,val fileSha256:String,val signedRegionSha256:String,val role:String) {
    fun metadata()=ImageMetadata(file,size,version,wireVersion,fileSha256,signedRegionSha256)
}
@Serializable data class ZigbeeOtaMetadata(val file:String,val size:Int,val fileSha256:String,val manufacturerCode:Int,val imageType:Int,val fileVersion:Long,val model:String,val profile:Int,val mainSignedRegionSha256:String)
@Serializable data class CommonManifest(val schemaVersion:Int,val bundleId:String,val minAppVersion:String,val model:String,val layoutVersion:Int,val identityProtocol:Int,
    val allowedLoaderSha256:List<String> = emptyList(),val legacyRecoverySignedHashes:List<String>,val targetRecoverySignedHash:String,val allowedSourceSignedHashes:List<String>,
    val main:CommonImage,val qualificationSha256:String,val recovery:CommonImage?=null,val migration:CommonImage?=null,val zigbeeOta:ZigbeeOtaMetadata?=null,
    val loaderContracts:List<LoaderContract> = emptyList(),val firstInstall:FirstInstallReference?=null,val stockRestore:CommonImage?=null,val stockBootstrap:CommonImage?=null)
@Serializable data class FirstInstallReference(val file:String,val size:Int,val sha256:String,val signatureFile:String,val signatureSha256:String)
data class RawCommonPackage(val manifest:ByteArray,val signature:ByteArray,val main:ByteArray,val bundleDigest:String,val recovery:ByteArray?=null,val migration:ByteArray?=null,val zigbeeOta:ByteArray?=null,val originalZip:ByteArray?=null)
data class ValidatedCommonPackage(val manifest:CommonManifest,val main:ByteArray,val bundleDigest:String,val recovery:ByteArray?=null,val migration:ByteArray?=null,val zigbeeOta:ByteArray?=null,
    val firstInstall:org.openvimar.installer.VerifiedCommonSet?=null) {
    /** Runtime adapter only. This derived object is never exported as a signed manifest. */
    fun bind(identity:RuntimeIdentity,address:String):ValidatedPackage {
        CommonPackageValidator.compatibleIdentity(manifest,identity)
        require(Regex("([0-9A-F]{2}:){5}[0-9A-F]{2}").matches(address)) {"Invalid Bluetooth target address"}
        val m=Manifest(2,manifest.bundleId,manifest.minAppVersion,Device("Vimar 30805","",identity.uid,address),
            manifest.legacyRecoverySignedHashes.firstOrNull() ?: "",manifest.targetRecoverySignedHash,manifest.allowedSourceSignedHashes,
            (manifest.migration ?: manifest.main).metadata(),manifest.main.metadata(),null)
        return ValidatedPackage(m,migration?.copyOf() ?: main.copyOf(),main.copyOf(),bundleDigest,identity.copy(uid=identity.uid.toList()),manifest)
    }
}
object CommonPackageReader {
    fun read(input:InputStream):RawCommonPackage {
        val bytes=PackageReader.bounded(input,PackageReader.MAX_ZIP)
        val (entries,digest)=PackageReader.entries(bytes.inputStream(),true)
        require(entries.keys.containsAll(listOf("manifest.json","manifest.sig","main.signed.bin"))) {"Missing ZIP entry"}
        val schema=Json.parseToJsonElement(entries.getValue("manifest.json").toString(Charsets.UTF_8)).jsonObject["schemaVersion"]
        if(schema!=JsonPrimitive(3))require(entries.keys.none{it in setOf("loader.bin","first-install.json","first-install.sig","stock-restore.signed.bin","stock-bootstrap.signed.bin")}){"Unexpected schema3 entry in legacy/common schema2 archive"}
        return RawCommonPackage(entries.getValue("manifest.json"),entries.getValue("manifest.sig"),entries.getValue("main.signed.bin"),digest,entries["recovery.signed.bin"],entries["migration.signed.bin"],entries["main.ota"],bytes)
    }
}
object CommonPackageValidator {
    private val json=Json { ignoreUnknownKeys=false; isLenient=false; coerceInputValues=false }
    private val hash=Regex("[0-9a-f]{64}")
    private fun hashes(values:List<String>,empty:Boolean=false) {
        require(values.size in (if(empty) 0 else 1)..64 && values==values.distinct().sorted() && values.all{hash.matches(it)}) {"Invalid hash allowlist"}
    }
    fun compatibleIdentity(m:CommonManifest,identity:RuntimeIdentity) {
        require(identity.model==m.model && identity.layoutVersion==m.layoutVersion) {"Runtime model/layout/identity protocol incompatible"}
        require(identity.uid.size==2 && identity.uid.all{Regex("[0-9a-f]{8}").matches(it)}) {"Malformed runtime UID"}
        if(m.schemaVersion==2) {
            require(identity.protocol==1&&identity.typedLoader==null&&identity.anchorSha256==null&&identity.loaderSha256 in m.allowedLoaderSha256) {"Runtime loader is not authorized by this release"}
        } else {
            require(m.schemaVersion==3&&m.identityProtocol==2)
            RuntimeIdentityLookup.validate(identity)
            val contract=if(identity.protocol==1)LoaderContract(LoaderContract.LEGACY,identity.loaderSha256) else requireNotNull(identity.typedLoader)
            require(contract in m.loaderContracts){"Typed runtime loader is not authorized by this release"}
        }
    }
    fun validate(raw:RawCommonPackage,key:PublicKey,appVersion:String):ValidatedCommonPackage {
        // RawPackage exposes JVM byte arrays. Freeze every input before JCA or
        // nested verification can call caller-provided objects or other code.
        require(raw.manifest.size<=65536&&raw.signature.size<=80&&raw.main.size<=PackageReader.MAX_IMAGE&&
            (raw.recovery?.size ?: 0)<=PackageReader.MAX_IMAGE&&(raw.migration?.size ?: 0)<=PackageReader.MAX_IMAGE&&
            (raw.zigbeeOta?.size ?: 0)<=ZigbeeCarrierValidator.MAX_CARRIER&&(raw.originalZip?.size ?: 0)<=PackageReader.MAX_ZIP){"Common package input exceeds supported bounds"}
        val owned=raw.copy(manifest=raw.manifest.copyOf(),signature=raw.signature.copyOf(),main=raw.main.copyOf(),recovery=raw.recovery?.copyOf(),
            migration=raw.migration?.copyOf(),zigbeeOta=raw.zigbeeOta?.copyOf(),originalZip=raw.originalZip?.copyOf())
        return validateOwned(owned,key,appVersion)
    }
    private fun validateOwned(raw:RawCommonPackage,key:PublicKey,appVersion:String):ValidatedCommonPackage {
        require(raw.manifest.size in 1..65536 && raw.signature.size in 1..80)
        val p=java.security.AlgorithmParameters.getInstance("EC").apply{init(java.security.spec.ECGenParameterSpec("secp256r1"))}.getParameterSpec(java.security.spec.ECParameterSpec::class.java)
        require(key is ECPublicKey && key.params.curve==p.curve && key.params.generator==p.generator && key.params.order==p.order && key.params.cofactor==p.cofactor) {"P256 key required"}
        val verifier=Signature.getInstance("SHA256withECDSA").apply{initVerify(key);update(raw.manifest)}
        require(verifier.verify(raw.signature)) {"Manifest signature invalid"}
        val text=raw.manifest.toString(Charsets.UTF_8);val tree=json.parseToJsonElement(text).jsonObject
        require((PackageValidator.canonical(tree)+"\n").toByteArray().contentEquals(raw.manifest)) {"Noncanonical manifest"}
        if(tree["schemaVersion"]==JsonPrimitive(3))return validateV3(raw,key,appVersion)
        require(tree.keys.all{it in setOf("schemaVersion","bundleId","minAppVersion","model","layoutVersion","identityProtocol","allowedLoaderSha256","legacyRecoverySignedHashes","targetRecoverySignedHash","allowedSourceSignedHashes","main","qualificationSha256","recovery","migration","zigbeeOta")}){"Unsupported schema2 manifest fields"}
        val m=json.decodeFromString<CommonManifest>(text)
        require(m.schemaVersion==2 && m.model=="VIMAR30805" && m.layoutVersion==2 && m.identityProtocol==1) {"Unsupported common contract"}
        require(PackageValidator.compatible(appVersion,m.minAppVersion)) {"Update the Android app before importing this release"}
        require(hash.matches(raw.bundleDigest) && hash.matches(m.bundleId) && hash.matches(m.qualificationSha256) && hash.matches(m.targetRecoverySignedHash))
        require(sha256((PackageValidator.canonical(JsonObject(tree.filterKeys{it!="bundleId"}))+"\n").toByteArray())==m.bundleId) {"Bundle identifier mismatch"}
        hashes(m.allowedLoaderSha256);hashes(m.allowedSourceSignedHashes);hashes(m.legacyRecoverySignedHashes,true)
        require((m.migration!=null)==m.legacyRecoverySignedHashes.isNotEmpty()) {"Migration/source recovery contract mismatch"}
        require((m.migration!=null)==(raw.migration!=null) && (m.recovery!=null)==(raw.recovery!=null) && (m.zigbeeOta!=null)==(raw.zigbeeOta!=null)) {"Manifest/ZIP component mismatch"}
        validateComponent(m.main,raw.main,"main",1,key)
        m.migration?.let{validateComponent(it,requireNotNull(raw.migration),"migration",3,key)}
        m.recovery?.let{validateComponent(it,requireNotNull(raw.recovery),"recovery",2,key);require(it.signedRegionSha256==m.targetRecoverySignedHash)}
        m.zigbeeOta?.let { ZigbeeCarrierValidator.validate(it,requireNotNull(raw.zigbeeOta),m.main) }
        return ValidatedCommonPackage(m,raw.main.copyOf(),raw.bundleDigest,raw.recovery?.copyOf(),raw.migration?.copyOf(),raw.zigbeeOta?.copyOf())
    }
    private fun validateV3(raw:RawCommonPackage,key:PublicKey,appVersion:String):ValidatedCommonPackage {
        val zip=requireNotNull(raw.originalZip){"Schema3 requires the original bounded ZIP"}
        val verified=org.openvimar.installer.CommonRelease.verify(zip,key,appVersion)
        val original=CommonPackageReader.read(zip.inputStream())
        fun equal(a:ByteArray?,b:ByteArray?)=(a==null&&b==null)||(a!=null&&b!=null&&a.contentEquals(b))
        require(raw.bundleDigest==original.bundleDigest&&raw.bundleDigest==verified.releaseSha256&&equal(raw.manifest,original.manifest)&&equal(raw.signature,original.signature)&&
            equal(raw.main,original.main)&&equal(raw.recovery,original.recovery)&&equal(raw.migration,original.migration)&&equal(raw.zigbeeOta,original.zigbeeOta)){"Schema3 original ZIP/component mismatch"}
        val m=json.decodeFromString<CommonManifest>(original.manifest.toString(Charsets.UTF_8))
        return ValidatedCommonPackage(m,original.main.copyOf(),original.bundleDigest,original.recovery?.copyOf(),original.migration?.copyOf(),original.zigbeeOta?.copyOf(),verified)
    }
    private fun tlvs(bytes:ByteArray,start:Int):Map<Int,ByteArray> {
        val b=ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
        val end=start+(b.getShort(start+2).toInt() and 65535);var offset=start+4;val result=mutableMapOf<Int,ByteArray>()
        while(offset<end) {val tag=b.getShort(offset).toInt() and 65535;val size=b.getShort(offset+2).toInt() and 65535;offset+=4;result[tag]=bytes.copyOfRange(offset,offset+size);offset+=size}
        return result
    }
    private fun validateComponent(meta:CommonImage,bytes:ByteArray,name:String,role:Int,key:PublicKey) {
        require(meta.role==name.uppercase()) {"Component role mismatch"}
        PackageValidator.validateImage(meta.metadata(),bytes,name+".signed.bin",true)
        val b=ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
        require((b.getShort(8).toInt() and 65535)==512 && b.getInt(4)==0 && b.getInt(28)==0) {"Unsupported header geometry"}
        val capacity=if(role==2) 0x34000 else 0xa2000
        val base=if(role==2) 0xb0000L else 0xc000L
        val payload=b.getInt(12)
        require(bytes.size<=capacity && payload>=8) {"Component exceeds authorized slot geometry"}
        val stack=b.getInt(512).toLong() and 0xffffffffL;val reset=b.getInt(516).toLong() and 0xffffffffL
        require(stack>0x20000000L && stack<=0x20040000L && stack%8==0L && reset and 1L==1L && (reset and 0xfffffffeL) in (base+512) until (base+512+payload)) {"Invalid component vector or target slot"}
        val protectedStart=512+b.getInt(12);val protectedSize=b.getShort(10).toInt() and 65535
        require(protectedSize>0) {"Authenticated role/profile required"}
        val protected=tlvs(bytes,protectedStart)
        require(protected.keys.all{it in setOf(0x50,0xa0,0xa1)} && (protected[0x50]==null || protected[0x50]?.size==4)) {"Unsupported protected TLV"}
        require(protected[0xa0]?.contentEquals("VIMAR30805".toByteArray()+byteArrayOf(2))==true && protected[0xa1]?.contentEquals(byteArrayOf(role.toByte()))==true) {"Authenticated role/profile mismatch"}
        val end=protectedStart+protectedSize;val unprotected=tlvs(bytes,end)
        val keyhash=java.security.MessageDigest.getInstance("SHA-256").digest(key.encoded)
        require(unprotected.keys==setOf(1,0x10,0x22) && unprotected[1]?.contentEquals(keyhash)==true) {"Image key hash or unprotected TLV contract mismatch"}
        val digest=java.security.MessageDigest.getInstance("SHA-256").digest(bytes.copyOfRange(0,end))
        require(unprotected[0x10]?.contentEquals(digest)==true) {"Image digest TLV mismatch"}
        val signature=unprotected[0x22] ?: error("Missing image signature")
        val verifier=Signature.getInstance("SHA256withECDSA").apply{initVerify(key);update(bytes,0,end)}
        require(verifier.verify(signature)) {"Image signature invalid"}
    }
}
/** BLE-reported identity over an authenticated bond; this is not hardware attestation. */
class IdentityBoundTransport(private val delegate:BleTransport,private val expected:RuntimeIdentity,private val manifest:CommonManifest):BleTransport,MigrationBootTransport {
    private suspend fun verify() {val observed=RuntimeIdentityLookup.forRelease(delegate,manifest);require(observed==expected) {"Runtime identity changed; select the target again"}}
    override suspend fun connect(address:String){delegate.connect(address);verify()}
    override suspend fun identity():RuntimeIdentity {verify();return expected}
    override suspend fun identityV2():RuntimeIdentity {verify();require(expected.protocol==2);return expected}
    override suspend fun images():RemoteImages {verify();return delegate.images()}
    override suspend fun upload(data:ByteArray,onAck:suspend(Int)->Unit){verify();delegate.upload(data,onAck)}
    override suspend fun reset():ResetAck {verify();return delegate.reset()}
    override suspend fun bootMigration(expectedHash:String):ResetAck {verify();return (delegate as? MigrationBootTransport ?: error("Purpose-specific migration boot transport unavailable")).bootMigration(expectedHash)}
    override suspend fun close()=delegate.close()
}
