package org.openvimar.updater.core

import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Called only after the canonical common manifest's signature and MAIN verify.
 * Authenticates publisher binding/bytes; does not claim raw-LZMA2 decompression.
 * The builder checks reconstruction; the target independently verifies/decompresses.
 */
object ZigbeeCarrierValidator {
    const val MAX_CARRIER=0xa2000+66
    fun validate(meta:ZigbeeOtaMetadata,bytes:ByteArray,main:CommonImage) {
        require(meta.file=="main.ota" && meta.size==bytes.size && bytes.size in 66+512..MAX_CARRIER) { "Invalid Zigbee carrier size/name" }
        require(meta.fileSha256.matches(Regex("[0-9a-f]{64}")) && sha256(bytes)==meta.fileSha256) { "Zigbee carrier hash mismatch" }
        require(meta.manufacturerCode==0xfff1 && meta.imageType==0x3085 && meta.model=="VIMAR30805" && meta.profile==2 && meta.mainSignedRegionSha256==main.signedRegionSha256 && main.role=="MAIN") { "Zigbee carrier model/profile/MAIN binding mismatch" }
        require(main.wireVersion.size==4 && main.wireVersion.all { it in 0..255 } && main.wireVersion[3]==0L)
        val version=main.wireVersion.fold(0L) { value,part -> (value shl 8) or part }
        require(meta.fileVersion==version && meta.fileVersion in 1..0xffffffffL) { "Zigbee wire version mismatch" }
        val b=ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
        fun u16(offset:Int)=b.getShort(offset).toInt() and 65535
        fun u32(offset:Int)=b.getInt(offset).toLong() and 0xffffffffL
        require(u32(0)==0x0beef11eL && u16(4)==0x100 && u16(6)==60 && u16(8)==4 && u16(10)==meta.manufacturerCode && u16(12)==meta.imageType && u32(14)==version && u16(18)==2 && u32(52)==bytes.size.toLong() && u16(56)==1 && u16(58)==1 && u16(60)==0 && u32(62)==bytes.size-66L) { "Unsupported Zigbee OTA envelope" }
        val image=bytes.copyOfRange(66,bytes.size);val c=ByteBuffer.wrap(image).order(ByteOrder.LITTLE_ENDIAN)
        require(c.getInt(0)==0x96f3b83d.toInt() && c.getInt(4)==0 && c.getShort(8).toInt() and 65535==512 && c.getInt(16)==0xc00 && c.getInt(28)==0) { "Unsupported compressed image header" }
        val compressed=c.getInt(12).toLong() and 0xffffffffL;val protectedSize=c.getShort(10).toInt() and 65535
        require(compressed>0 && compressed+512+protectedSize+4<=image.size)
        require(listOf((image[20].toInt() and 255).toLong(),(image[21].toInt() and 255).toLong(),(c.getShort(22).toInt() and 65535).toLong(),c.getInt(24).toLong() and 0xffffffffL)==main.wireVersion)
        fun tlvs(start:Int,magic:Int,size:Int?=null):Pair<Map<Int,ByteArray>,Int> {
            require(start>=512 && start+4<=image.size)
            val total=c.getShort(start+2).toInt() and 65535
            require(c.getShort(start).toInt() and 65535==magic && total>=4 && total<=image.size-start && (size==null || size==total))
            var offset=start+4;val end=start+total;val result=mutableMapOf<Int,ByteArray>()
            while(offset<end) {
                require(offset+4<=end);val tag=c.getShort(offset).toInt() and 65535;val length=c.getShort(offset+2).toInt() and 65535;offset+=4
                require(tag !in result && length<=end-offset);result[tag]=image.copyOfRange(offset,offset+length);offset+=length
            }
            return result to end
        }
        val (protected,end)=tlvs(512+compressed.toInt(),0x6908,protectedSize)
        require(protected.keys==setOf(0x70,0x71,0x72,0xa0,0xa1) || protected.keys==setOf(0x50,0x70,0x71,0x72,0xa0,0xa1)) { "Unsupported compressed protected TLVs" }
        require(protected[0x50]==null || protected[0x50]?.size==4)
        require(protected[0xa0]!!.contentEquals("VIMAR30805\u0002".toByteArray()) && protected[0xa1]!!.contentEquals(byteArrayOf(1))) { "Compressed target role/profile mismatch" }
        require(protected[0x70]!!.size==4 && ByteBuffer.wrap(protected[0x70]!!).order(ByteOrder.LITTLE_ENDIAN).int in 8..0xa2000 && protected[0x72]!!.size in 8..72)
        require(protected[0x71]!!.joinToString("") { "%02x".format(it.toInt() and 255) }==meta.mainSignedRegionSha256) { "Compressed inner MAIN binding mismatch" }
        val (unprotected,finished)=tlvs(end,0x6907)
        require(finished==image.size && unprotected.keys==setOf(1,0x10,0x22) && unprotected[1]!!.size==32 && unprotected[0x10]!!.size==32 && unprotected[0x22]!!.size in 8..72) { "Unsupported compressed signature TLVs" }
    }
}
