package org.openvimar.installer

import java.security.AlgorithmParameters
import java.security.KeyFactory
import java.security.PublicKey
import java.security.Signature
import java.security.interfaces.ECPublicKey
import java.security.spec.ECGenParameterSpec
import java.security.spec.ECParameterSpec
import java.security.spec.X509EncodedKeySpec
import org.openvimar.updater.core.CommonImage
import org.openvimar.updater.core.ImageMetadata
import org.openvimar.updater.core.PackageValidator
import org.openvimar.updater.core.ZigbeeCarrierValidator
import org.openvimar.updater.core.ZigbeeOtaMetadata

/** Immutable public artifact authority. No UID or per-unit executable is input. */
class VerifiedCommonSet internal constructor(val releaseSha256:String,val familySha256:String,
    loader:ByteArray,main:ByteArray,recovery:ByteArray,descriptor:ByteArray,val watchdogHandoff:String?=null) {
    private val loaderBytes=loader.copyOf();private val mainBytes=main.copyOf();private val recoveryBytes=recovery.copyOf()
    private val descriptorBytes=descriptor.copyOf()
    fun loader()=loaderBytes.copyOf()
    fun main()=mainBytes.copyOf()
    fun recovery()=recoveryBytes.copyOf()
    fun descriptor()=descriptorBytes.copyOf()
    fun authorizeWatchdogHandoff(target:TargetIdentity,generation:Long):WatchdogHandoffAuthority?=watchdogHandoff?.let{
        WatchdogHandoffAuthority.fromSignedDescriptor(it,releaseSha256,familySha256,target,generation)}
}
object CommonRelease {
    private val required=setOf("schemaVersion","bundleId","minAppVersion","model","layoutVersion","identityProtocol","loaderContracts",
        "legacyRecoverySignedHashes","targetRecoverySignedHash","allowedSourceSignedHashes","main","recovery","qualificationSha256","firstInstall")
    private val optional=setOf("migration","zigbeeOta","stockRestore","stockBootstrap")
    private val limits=mapOf("manifest.json" to 65536,"manifest.sig" to 80,"first-install.json" to 16384,"first-install.sig" to 80,
        "loader.bin" to 0xc000,"main.signed.bin" to 0xa2000,"recovery.signed.bin" to 0x34000,"migration.signed.bin" to 0xa2000,
        "stock-restore.signed.bin" to 0x3f000,"stock-bootstrap.signed.bin" to 0xa2000,"main.ota" to ZigbeeCarrierValidator.MAX_CARRIER)
    private val baseEntries=setOf("manifest.json","manifest.sig","first-install.json","first-install.sig","loader.bin","main.signed.bin","recovery.signed.bin")
    fun verify(raw:ByteArray,publicKey:PublicKey,appVersion:String):VerifiedCommonSet=verifyMode(raw,publicKey,appVersion,false).first
    internal fun inspectCandidate(raw:ByteArray,publicKey:PublicKey,appVersion:String):Pair<VerifiedCommonSet,ByteArray> {
        val result=verifyMode(raw,publicKey,appVersion,true);return result.first to requireNotNull(result.second)
    }
    /** Local owner-reviewed input has no release/qualification authority.
     * Only outer artifact signatures may be absent: loader compatibility,
     * image signatures, protected model/role tags and every digest stay checked. */
    internal fun inspectLocal(raw:ByteArray,publicKey:PublicKey,appVersion:String):Pair<VerifiedCommonSet,ByteArray> {
        val entries=StrictZip.read(raw,limits+("qualification.json" to 65536),2*1024*1024,setOf("manifest.json"),2*1024*1024)
        val beta=obj(StrictJson.parse(entries.getValue("manifest.json")))["purpose"]=="qualification-candidate"
        val result=verifyMode(raw,publicKey,appVersion,beta,true)
        return result.first to (result.second?:byteArrayOf())
    }
    private fun verifyMode(raw:ByteArray,publicKey:PublicKey,appVersion:String,candidate:Boolean,local:Boolean=false):Pair<VerifiedCommonSet,ByteArray?> {
        val bytes=raw.copyOf();val expectedBase=(if(local)baseEntries-setOf("manifest.sig","first-install.sig") else baseEntries)+(if(candidate)setOf("qualification.json") else emptySet())
        val entries=StrictZip.read(bytes,if(candidate)limits+("qualification.json" to 65536) else limits,2*1024*1024,expectedBase,2*1024*1024)
        // Freeze caller-supplied public-key encoding before any JCA use.
        val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(publicKey.encoded.copyOf()))
        val p=AlgorithmParameters.getInstance("EC").apply{init(ECGenParameterSpec("secp256r1"))}.getParameterSpec(ECParameterSpec::class.java)
        require(key is ECPublicKey&&key.params.curve==p.curve&&key.params.generator==p.generator&&key.params.order==p.order&&key.params.cofactor==p.cofactor){"Pinned P256 public key required"}
        val manifestBytes=entries.getValue("manifest.json")
        if(!local)signature(key,manifestBytes,entries.getValue("manifest.sig"))
        val m=obj(StrictJson.parse(manifestBytes))
        val requiredFields=required+(if(candidate)setOf("purpose") else emptySet())
        require(m.keys.containsAll(requiredFields)&&(m.keys-requiredFields).all{it in optional}){"Unsupported schema3 fields"}
        if(candidate)require(m["purpose"]=="qualification-candidate")
        require((StrictJson.canonical(m)+"\n").toByteArray().contentEquals(manifestBytes)){"Noncanonical signed manifest"}
        require(m["schemaVersion"]==3L&&m["model"]=="VIMAR30805"&&m["layoutVersion"]==2L&&m["identityProtocol"]==2L)
        require(version(appVersion)>=version(m["minAppVersion"] as? String?:error("Missing app version")))
        require(hash(m["bundleId"])==sha256((StrictJson.canonical(m.filterKeys{it!="bundleId"})+"\n").toByteArray())){"Bundle ID mismatch"}
        hash(m["qualificationSha256"]);val recoveryHash=hash(m["targetRecoverySignedHash"])
        hashes(m["allowedSourceSignedHashes"],false)
        val legacy=hashes(m["legacyRecoverySignedHashes"],true)
        require(("migration" in m)==legacy.isNotEmpty())
        require(("stockRestore" in m)==("stockBootstrap" in m))
        val contracts=records(m["loaderContracts"])
        val main=component(m["main"],entries.getValue("main.signed.bin"),"main.signed.bin",1,0xc000,0xa2000,key)
        val recovery=component(m["recovery"],entries.getValue("recovery.signed.bin"),"recovery.signed.bin",2,0xb0000,0x34000,key)
        require(recovery.signedRegionSha256==recoveryHash)
        val expectedEntries=expectedBase.toMutableSet()
        val componentHashes=mutableMapOf("main" to main.fileSha256,"recovery" to recovery.fileSha256)
        listOf(Triple("migration","migration.signed.bin",3),Triple("stockRestore","stock-restore.signed.bin",4),Triple("stockBootstrap","stock-bootstrap.signed.bin",3)).forEach{(field,file,role)->
            if(field in m){expectedEntries+=file;componentHashes[field]=component(m[field],entries.getValue(file),file,role,if(role==4)0xb0000 else 0xc000,if(role==4)0x3f000 else 0xa2000,key).fileSha256}}
        if("zigbeeOta" in m){expectedEntries+="main.ota";val o=keys(m["zigbeeOta"],setOf("file","size","fileSha256","manufacturerCode","imageType","fileVersion","model","profile","mainSignedRegionSha256"))
            ZigbeeCarrierValidator.validate(ZigbeeOtaMetadata(o["file"] as String,integer(o["size"]),hash(o["fileSha256"]),integer(o["manufacturerCode"]),integer(o["imageType"]),o["fileVersion"] as Long,o["model"] as String,integer(o["profile"]),hash(o["mainSignedRegionSha256"])),entries.getValue("main.ota"),main);componentHashes["zigbeeOta"]=hash(o["fileSha256"])}
        require((if(local)entries.keys-setOf("manifest.sig","first-install.sig") else entries.keys)==expectedEntries){"Manifest/ZIP entry mismatch"}
        val binding=keys(m["firstInstall"],setOf("file","size","sha256","signatureFile","signatureSha256"))
        val descriptorBytes=entries.getValue("first-install.json");val descriptorSignature=entries["first-install.sig"]
        require(binding["file"]=="first-install.json"&&binding["signatureFile"]=="first-install.sig"&&binding["size"]==descriptorBytes.size.toLong()&&
            hash(binding["sha256"])==sha256(descriptorBytes))
        hash(binding["signatureSha256"])
        if(!local)require(hash(binding["signatureSha256"])==sha256(requireNotNull(descriptorSignature)))
        if(!local)signature(key,descriptorBytes,requireNotNull(descriptorSignature))
        val d=obj(StrictJson.parse(descriptorBytes));val descriptorFields=setOf("schemaVersion","type","model","layoutVersion","identityProtocol","loaderContracts","images")
        require(d.keys.containsAll(descriptorFields)&&(d.keys-descriptorFields).all{it=="watchdogHandoff"})
        val watchdog=if("watchdogHandoff" in d){require(d["watchdogHandoff"]==WatchdogHandoffAuthority.POLICY);d.getValue("watchdogHandoff") as String}else null
        require((StrictJson.canonical(d)+"\n").toByteArray().contentEquals(descriptorBytes)&&d["schemaVersion"]==1L&&d["type"]=="vimar30805-common-first-install"&&d["model"]=="VIMAR30805"&&d["layoutVersion"]==2L&&d["identityProtocol"]==2L)
        val images=keys(d["images"],setOf("loader","main","recovery"));val loader=entries.getValue("loader.bin")
        require(loader.size==AnchorV1.LOADER&&(AnchorV1.ANCHOR until AnchorV1.LOADER).all{loader[it]==0xff.toByte()}){"Canonical loader requires erased anchor placeholder"}
        exact(images["loader"],mapOf("file" to "loader.bin","size" to loader.size.toLong(),"sha256" to sha256(loader)))
        val stack=word(loader,0);val reset=word(loader,4)
        require(stack>0x20000000L&&stack<=0x20040000L&&stack%8==0L&&reset and 1L==1L&&(reset and 0xfffffffeL) in 8L until AnchorV1.CODE.toLong())
        val family=AnchorV1.family(loader.copyOfRange(0,AnchorV1.CODE));val selected=mapOf("kind" to AnchorV1.COMMON,"sha256" to family)
        require(records(d["loaderContracts"])==listOf(selected)&&selected in contracts){"Typed loader family is not exactly authorized"}
        fun inner(meta:CommonImage)=mapOf("file" to meta.file,"size" to meta.size.toLong(),"sha256" to meta.fileSha256,"signedRegionSha256" to meta.signedRegionSha256,"role" to meta.role,"version" to meta.version)
        exact(images["main"],inner(main));exact(images["recovery"],inner(recovery))
        val qualification=if(candidate)entries.getValue("qualification.json").also{report->
            require(sha256(report)==m["qualificationSha256"]){"Candidate qualification report hash mismatch"}
            val checks=setOf("zigbee_ota_completed","postboot_hash_verified","ble_recovery_verified","power_cut_recovery_verified",
                "split_stage_verified","loader_binding_verified","recovery_tail_preserved","mixed_profile_rejected","protection_flash_radio_verified",
                "stock_restore_verified","migration_verified","commonFirstFlashVerified","stockRestoreVerified")
            val q=keys(StrictJson.parse(report),setOf("schemaVersion","model","layoutVersion","loaderContracts","components")+checks)
            require(q["schemaVersion"]==3L&&q["model"]=="VIMAR30805"&&q["layoutVersion"]==2L&&records(q["loaderContracts"])==contracts&&checks.all{q[it]===false}){"Candidate must retain every pending qualification flag as literal false"}
            componentHashes["loader"]=sha256(loader);require(obj(q["components"])==componentHashes){"Candidate report components differ from actual signed assets"}
        }else null
        // A manually admitted unsigned envelope cannot manufacture a signed
        // watchdog capability. A separately valid descriptor still authenticates
        // that capability even when the outer manifest signature is absent.
        val authenticatedWatchdog=if(!local||descriptorSignature!=null&&runCatching{signature(key,descriptorBytes,descriptorSignature)}.isSuccess)watchdog else null
        return VerifiedCommonSet(sha256(bytes),family,loader,entries.getValue("main.signed.bin"),entries.getValue("recovery.signed.bin"),descriptorBytes,authenticatedWatchdog) to qualification
    }
    private fun signature(key:PublicKey,bytes:ByteArray,sig:ByteArray){require(sig.size in 8..80);require(Signature.getInstance("SHA256withECDSA").run{initVerify(key);update(bytes);verify(sig)}){"Project signature mismatch"}}
    private fun hash(value:Any?):String {require(value is String&&Regex("[0-9a-f]{64}").matches(value));return value}
    private fun integer(value:Any?):Int {require(value is Long&&value in 0..Int.MAX_VALUE.toLong());return value.toInt()}
    private data class Version(val a:Long,val b:Long,val c:Long):Comparable<Version> {
        override fun compareTo(other:Version):Int=compareValuesBy(this,other,Version::a,Version::b,Version::c)
    }
    private fun version(value:String):Version {require(Regex("(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)").matches(value));val p=value.split('.').map{it.toLong()};return Version(p[0],p[1],p[2])}
    private fun hashes(value:Any?,empty:Boolean):List<String> {require(value is List<*> && value.size in (if(empty)0 else 1)..64);val out=value.map(::hash);require(out==out.distinct().sorted());return out}
    private fun records(value:Any?):List<Map<String,String>> {
        require(value is List<*>&&value.size in 1..64)
        val out=value.map{item->val m=keys(item,setOf("kind","sha256"));require(m["kind"] in setOf(AnchorV1.COMMON,AnchorV1.LEGACY));mapOf("kind" to m["kind"] as String,"sha256" to hash(m["sha256"]))}
        require(out.distinct().size==out.size&&out==out.sortedWith(compareBy({it.getValue("kind")},{it.getValue("sha256")})));return out
    }
    private fun component(value:Any?,bytes:ByteArray,file:String,role:Int,base:Int,capacity:Int,key:PublicKey):CommonImage {
        val m=keys(value,setOf("file","size","version","wireVersion","fileSha256","signedRegionSha256","role"))
        val wire=m["wireVersion"] as? List<*>;require(wire!=null&&wire.size==4&&wire.all{it is Long})
        val roleName=mapOf(1 to "MAIN",2 to "RECOVERY",3 to "MIGRATION",4 to "RESTORE").getValue(role)
        require(m["role"]==roleName&&bytes.size<=capacity)
        val meta=ImageMetadata(m["file"] as String,integer(m["size"]),m["version"] as String,wire.map{it as Long},hash(m["fileSha256"]),hash(m["signedRegionSha256"]))
        // Reuse unchanged audited core header/TLV/duplicate/hash/version bounds.
        PackageValidator.validateImage(meta,bytes,file,true)
        require(word(bytes,4)==0L&&((bytes[8].toInt() and 255) or ((bytes[9].toInt() and 255) shl 8))==512&&word(bytes,28)==0L)
        val payload=word(bytes,12).toInt();require(payload>=8)
        val stack=word(bytes,512);val reset=word(bytes,516)
        require(stack>0x20000000L&&stack<=0x20040000L&&stack%8==0L&&reset and 1L==1L&&(reset and 0xfffffffeL) in (base+512L) until (base+512L+payload))
        val protSize=(bytes[10].toInt() and 255) or ((bytes[11].toInt() and 255) shl 8);require(protSize>0)
        val end=512+payload+protSize;val protected=tlvs(bytes,512+payload,end)
        require(protected.keys.all{it in setOf(0x50,0xa0,0xa1)}&&(protected[0x50]==null||protected[0x50]?.size==4))
        require(protected[0xa0]?.contentEquals("VIMAR30805".toByteArray()+byteArrayOf(2))==true&&protected[0xa1]?.contentEquals(byteArrayOf(role.toByte()))==true)
        val ordinary=tlvs(bytes,end,bytes.size);require(ordinary.keys==setOf(1,0x10,0x22)&&ordinary[1]?.contentEquals(unhex(sha256(key.encoded)))==true)
        require(ordinary[0x10]?.contentEquals(unhex(meta.signedRegionSha256))==true)
        signature(key,bytes.copyOfRange(0,end),requireNotNull(ordinary[0x22]))
        return CommonImage(meta.file,meta.size,meta.version,meta.wireVersion,meta.fileSha256,meta.signedRegionSha256,roleName)
    }
    private fun tlvs(bytes:ByteArray,start:Int,end:Int):Map<Int,ByteArray> {
        // Prior core validation has established exact extents and unique tags;
        // these checks also keep this accessor safe independently of that fact.
        require(start>=0&&start<=end-4&&end<=bytes.size);var p=start+4;val result=linkedMapOf<Int,ByteArray>()
        while(p<end){require(p<=end-4);val tag=(bytes[p].toInt() and 255) or ((bytes[p+1].toInt() and 255) shl 8);val size=(bytes[p+2].toInt() and 255) or ((bytes[p+3].toInt() and 255) shl 8);p+=4
            require(tag !in result&&size<=end-p);result[tag]=bytes.copyOfRange(p,p+size);p+=size}
        require(p==end);return result
    }
}
