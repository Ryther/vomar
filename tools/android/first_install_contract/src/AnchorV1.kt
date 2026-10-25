package org.openvimar.installer

import java.security.MessageDigest
import java.util.zip.CRC32

internal fun sha256(bytes:ByteArray):String=MessageDigest.getInstance("SHA-256").digest(bytes)
    .joinToString(""){"%02x".format(it.toInt() and 255)}
internal fun unhex(value:String):ByteArray {
    require(Regex("[0-9a-f]{64}").matches(value)){"Exact lower-case SHA256 required"}
    return ByteArray(32){value.substring(it*2,it*2+2).toInt(16).toByte()}
}
internal fun word(bytes:ByteArray,offset:Int):Long {
    require(offset>=0&&offset<=bytes.size-4)
    return (0..3).fold(0L){v,i->v or ((bytes[offset+i].toLong() and 255) shl (8*i))}
}
internal fun putWord(bytes:ByteArray,offset:Int,value:Long) {
    require(value in 0..0xffffffffL)
    repeat(4){bytes[offset+it]=(value ushr (8*it)).toByte()}
}
internal object AnchorV1 {
    const val FLASH=0x100000
    const val PAGE=4096
    const val CODE=0xb000
    const val ANCHOR=0xb000
    const val LOADER=0xc000
    const val TABLE=8192
    const val SCRATCH_START=0xb0000
    const val SCRATCH_END=0xef000
    const val COMMIT_OFFSET=252
    const val COMMIT=0xa60c17edL
    const val COMMON="common-code44k-anchor-v1"
    const val LEGACY="legacy-full48k-sha256"
    private val domain="VIMAR30805-LOADER-CODE44K-ANCHOR1\u0000".toByteArray(Charsets.US_ASCII)
    fun encode(variant:Long,uid0:Long,uid1:Long,flashSha:String,uicrSha:String,tableSha:String):ByteArray {
        require(variant in 1..0xfffffffeL&&uid0 in 0..0xffffffffL&&uid1 in 0..0xffffffffL)
        val page=ByteArray(PAGE){0xff.toByte()}
        "VAR1".toByteArray(Charsets.US_ASCII).copyInto(page)
        page[4]=1;page[5]=0;page[6]=0;page[7]=1
        listOf(8 to 1L,12 to 2L,16 to 0x52840L,20 to variant,24 to uid0,28 to uid1,
            32 to FLASH.toLong(),36 to PAGE.toLong(),40 to 0x40000L,44 to PAGE.toLong(),48 to TABLE.toLong())
            .forEach{(offset,value)->putWord(page,offset,value)}
        "VIMAR30805\u0000\u0000".toByteArray(Charsets.US_ASCII).copyInto(page,52)
        unhex(flashSha).copyInto(page,64);unhex(uicrSha).copyInto(page,96);unhex(tableSha).copyInto(page,128)
        putWord(page,248,CRC32().apply{update(page,0,248)}.value)
        putWord(page,COMMIT_OFFSET,COMMIT)
        return page
    }
    fun table(original:ByteArray):ByteArray {
        require(original.size==FLASH)
        require((SCRATCH_START until SCRATCH_END).all{original[it]==0xff.toByte()}){"Original scratch is not erased; generic RESTORE is unsupported"}
        return ByteArray(TABLE).also{table->repeat(FLASH/PAGE){i->
            unhex(sha256(original.copyOfRange(i*PAGE,(i+1)*PAGE))).copyInto(table,i*32)
        }}
    }
    fun family(code:ByteArray):String {
        require(code.size==CODE){"Exactly44KiB loader code required"}
        return sha256(domain+code)
    }
}
