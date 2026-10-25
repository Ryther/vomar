package org.openvimar.updater.core

import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.*
import org.junit.Test

class ZigbeeCarrierTest {
    private val main=CommonImage("main.signed.bin",900,"0.6.1",listOf(0,6,1,0),"a".repeat(64),"b".repeat(64),"MAIN")
    private fun carrier():ByteArray {
        val image=ByteArray(512+12+142+150)
        val b=ByteBuffer.wrap(image).order(ByteOrder.LITTLE_ENDIAN)
        b.putInt(0,0x96f3b83d.toInt());b.putShort(8,512);b.putShort(10,142);b.putInt(12,12);b.putInt(16,0xc00);image[21]=6; b.putShort(22,1)
        var p=524; b.putShort(p,0x6908); b.putShort(p+2,142);p+=4
        fun tlv(tag:Int,data:ByteArray) { b.putShort(p,tag.toShort());b.putShort(p+2,data.size.toShort());System.arraycopy(data,0,image,p+4,data.size);p+=4+data.size }
        tlv(0x70,ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putInt(200).array())
        tlv(0x71,ByteArray(32){0xbb.toByte()});tlv(0x72,ByteArray(70));tlv(0xa0,"VIMAR30805\u0002".toByteArray());tlv(0xa1,byteArrayOf(1))
        // The carrier's digest/signature is publisher-bound by the signed manifest; test image is structural only.
        b.putShort(p,0x6907);b.putShort(p+2,(image.size-p).toShort());p+=4
        tlv(0x10,ByteArray(32));tlv(1,ByteArray(32));tlv(0x22,ByteArray(image.size-p-4))
        val ota=ByteArray(66)+image;val o=ByteBuffer.wrap(ota).order(ByteOrder.LITTLE_ENDIAN)
        o.putInt(0,0x0beef11e);o.putShort(4,0x100);o.putShort(6,60);o.putShort(8,4);o.putShort(10,0xfff1.toShort());o.putShort(12,0x3085)
        o.putInt(14,0x00060100);o.putShort(18,2);o.putInt(52,ota.size);o.putShort(56,1);o.putShort(58,1);o.putShort(60,0);o.putInt(62,image.size)
        return ota
    }
    private fun meta(bytes:ByteArray)=ZigbeeOtaMetadata("main.ota",bytes.size,sha256(bytes),0xfff1,0x3085,0x00060100,"VIMAR30805",2,main.signedRegionSha256)
    @Test fun publisherBoundCarrierChecksHeaderRoleProfileAndInnerMainDigestWithoutClaimingDecode() {
        val bytes=carrier();ZigbeeCarrierValidator.validate(meta(bytes),bytes,main)
        for(offset in listOf(0,4,6,8,10,12,14,18,52,56,58,60,62,66+16,66+524+4+8+4)) {
            val bad=bytes.copyOf();bad[offset]=(bad[offset].toInt() xor 1).toByte()
            assertThrows("offset $offset",IllegalArgumentException::class.java) { ZigbeeCarrierValidator.validate(meta(bad),bad,main) }
        }
        assertThrows(Exception::class.java) { ZigbeeCarrierValidator.validate(meta(bytes).copy(mainSignedRegionSha256="c".repeat(64)),bytes,main) }
        assertThrows(Exception::class.java) { ZigbeeCarrierValidator.validate(meta(bytes).copy(profile=1),bytes,main) }
        val bad=bytes.copyOf().also { it[it.lastIndex]=(it.last().toInt() xor 1).toByte() }
        assertThrows(Exception::class.java) { ZigbeeCarrierValidator.validate(meta(bytes),bad,main) }
    }

    @Test fun validatesActualEphemeralSignedPythonCarrierFixtureAndRejectsMissingOrTamperedBytes() {
        val root=java.io.File("../test-fixtures")
        val key=java.security.KeyFactory.getInstance("EC").generatePublic(java.security.spec.X509EncodedKeySpec(java.io.File(root,"synthetic-common-ota-public.der").readBytes()))
        val raw=java.io.File(root,"synthetic-common-ota.zip").inputStream().use(CommonPackageReader::read)
        val pkg=CommonPackageValidator.validate(raw,key,"0.4.0")
        assertNotNull(pkg.zigbeeOta);assertEquals(pkg.manifest.main.signedRegionSha256,pkg.manifest.zigbeeOta!!.mainSignedRegionSha256)
        assertThrows(Exception::class.java) { CommonPackageValidator.validate(raw.copy(zigbeeOta=null),key,"0.4.0") }
        assertThrows(Exception::class.java) { CommonPackageValidator.validate(raw.copy(zigbeeOta=raw.zigbeeOta!!.copyOf().apply { this[lastIndex]=(last().toInt() xor 1).toByte() }),key,"0.4.0") }
    }
}
