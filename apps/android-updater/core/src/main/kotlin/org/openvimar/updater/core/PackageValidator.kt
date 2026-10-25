package org.openvimar.updater.core

import java.security.PublicKey
import java.security.Signature
import java.security.interfaces.ECPublicKey
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlinx.serialization.json.*
import kotlinx.serialization.encodeToString

object PackageValidator {
    private val json=Json { ignoreUnknownKeys=false; isLenient=false; coerceInputValues=false }
    private val hash=Regex("[0-9a-f]{64}")
    private fun version(s:String):List<Long> {
        require(Regex("(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)").matches(s)) {"Invalid app/version triple"}
        return s.split('.').map { it.toLong() }
    }
    internal fun compatible(actual:String,minimum:String):Boolean {
        val a=version(actual); val b=version(minimum)
        for(i in 0..2) { if(a[i]!=b[i]) return a[i]>b[i] }; return true
    }
    fun signedRegionHash(bytes:ByteArray):String {
        val end=signedEnd(bytes)
        return sha256(bytes.copyOfRange(0,end))
    }
    private fun signedEnd(bytes:ByteArray):Int {
        require(bytes.size in 32..PackageReader.MAX_IMAGE) {"Invalid image size"}
        val b=ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
        require(b.getInt(0)==0x96f3b83d.toInt()) {"Invalid MCUboot magic"}
        val header=b.getShort(8).toInt() and 65535
        val protected=b.getShort(10).toInt() and 65535
        val payload=b.getInt(12).toLong() and 0xffffffffL
        require(b.getInt(16)==0) {"Unsupported image flags"}
        require(header>=32 && payload>0) {"Invalid MCUboot header"}
        val end=header.toLong()+payload+protected
        require(end<=bytes.size && end>=32) {"Truncated signed region"}
        if(protected>0) {
            require(protected>=4)
            val start=header.toLong()+payload
            require((b.getShort(start.toInt()).toInt() and 65535)==0x6908)
            require((b.getShort(start.toInt()+2).toInt() and 65535)==protected)
            validateTlvs(bytes,start.toInt(),end.toInt())
        }
        // Ordinary signed images have an unprotected TLV area after the authenticated region.
        require(end+4<=bytes.size)
        require((b.getShort(end.toInt()).toInt() and 65535)==0x6907)
        val tlvSize=b.getShort(end.toInt()+2).toInt() and 65535
        require(tlvSize>=4 && end+tlvSize==bytes.size.toLong()) {"Truncated unprotected TLVs"}
        validateTlvs(bytes,end.toInt(),bytes.size)
        return end.toInt()
    }
    private fun validateTlvs(bytes:ByteArray,start:Int,end:Int) {
        var pos=start+4
        val tags=mutableSetOf<Int>()
        while(pos<end) {
            require(pos+4<=end)
            val tag=(bytes[pos].toInt() and 255) or ((bytes[pos+1].toInt() and 255) shl 8)
            require(tags.add(tag)) {"Duplicate TLV"}
            val length=(bytes[pos+2].toInt() and 255) or ((bytes[pos+3].toInt() and 255) shl 8)
            pos+=4; require(length<=end-pos); pos+=length
        }
        require(pos==end)
    }
    internal fun canonical(value:JsonElement):String = when(value) {
        is JsonObject -> value.entries.sortedBy { it.key }.joinToString(",", "{", "}") { canonical(JsonPrimitive(it.key))+":"+canonical(it.value) }
        is JsonArray -> value.joinToString(",", "[", "]") { canonical(it) }
        is JsonPrimitive -> if(value.isString) json.encodeToString(value.content).map { ch ->
            if(ch.code>=127) "\\u%04x".format(ch.code) else ch.toString()
        }.joinToString("") else value.toString()
    }
    fun validate(raw:RawPackage,publicKey:PublicKey,appVersion:String):ValidatedPackage {
        require(raw.manifest.size in 1..65536 && raw.signature.size in 1..80)
        val parameters=java.security.AlgorithmParameters.getInstance("EC").apply {
            init(java.security.spec.ECGenParameterSpec("secp256r1"))
        }.getParameterSpec(java.security.spec.ECParameterSpec::class.java)
        require(publicKey is ECPublicKey && publicKey.params.curve==parameters.curve &&
            publicKey.params.generator==parameters.generator && publicKey.params.order==parameters.order &&
            publicKey.params.cofactor==parameters.cofactor) {"P256 key required"}
        val verifier=Signature.getInstance("SHA256withECDSA")
        verifier.initVerify(publicKey); verifier.update(raw.manifest)
        require(verifier.verify(raw.signature)) {"Manifest signature invalid"}
        val m=json.decodeFromString<Manifest>(raw.manifest.toString(Charsets.UTF_8))
        val tree=json.parseToJsonElement(raw.manifest.toString(Charsets.UTF_8)).jsonObject
        require((canonical(tree)+"\n").toByteArray().contentEquals(raw.manifest)) {"Noncanonical manifest"}
        require(sha256((canonical(JsonObject(tree.filterKeys { it!="bundleId" }))+"\n").toByteArray())==m.bundleId) {"Bundle identifier mismatch"}
        require(m.schemaVersion==1 && compatible(appVersion,m.minAppVersion))
        require(hash.matches(raw.bundleDigest) && hash.matches(m.bundleId))
        require(m.device.name.isNotBlank() && m.device.name.length<=128)
        require(Regex("[0-9a-f]{16}").matches(m.device.ieee))
        require(m.device.uid.size==2 && m.device.uid.all { Regex("[0-9a-f]{8}").matches(it) })
        require(Regex("([0-9A-F]{2}:){5}[0-9A-F]{2}").matches(m.device.bleAddress))
        require(hash.matches(m.legacyRecoverySignedHash) && hash.matches(m.targetRecoverySignedHash))
        require(m.allowedSourceSignedHashes.size in 1..64 && m.allowedSourceSignedHashes==m.allowedSourceSignedHashes.distinct().sorted() && m.allowedSourceSignedHashes.all { hash.matches(it) })
        with(requireNotNull(m.provenance) {"Schema1 provenance required"}) { require(listOf(deviceDescriptorSha256,otaReleaseSha256,qualificationSha256,migrationInputSha256,migrationReportSha256).all { hash.matches(it) }) }
        validateImage(m.migration,raw.migration,"migration.signed.bin",false)
        validateImage(m.main,raw.main,"main.signed.bin",true)
        return ValidatedPackage(m,raw.migration.copyOf(),raw.main.copyOf(),raw.bundleDigest)
    }
    internal fun validateImage(meta:ImageMetadata,bytes:ByteArray,name:String,main:Boolean) {
        require(meta.file==name && meta.size==bytes.size && meta.size in 1..PackageReader.MAX_IMAGE)
        require(hash.matches(meta.fileSha256) && hash.matches(meta.signedRegionSha256))
        require(sha256(bytes)==meta.fileSha256 && signedRegionHash(bytes)==meta.signedRegionSha256) {"Image hash mismatch"}
        val b=ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
        val wire=listOf((bytes[20].toInt() and 255).toLong(),(bytes[21].toInt() and 255).toLong(),(b.getShort(22).toInt() and 65535).toLong(), b.getInt(24).toLong() and 0xffffffffL)
        require(meta.wireVersion==wire) {"Wire version mismatch"}
        val display=wire.take(3).joinToString(".")
        require(if(main) wire[3]==0L && meta.version==display else meta.version==display+"+"+wire[3])
    }
}
