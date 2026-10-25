package org.openvimar.updater.core

import java.io.InputStream
import java.io.ByteArrayOutputStream
import org.apache.commons.compress.archivers.zip.ZipFile
import org.apache.commons.compress.utils.SeekableInMemoryByteChannel

object PackageReader {
    const val MAX_ZIP=2*1024*1024
    const val MAX_IMAGE=0xa4000
    private val limits=linkedMapOf("manifest.json" to 65536,"manifest.sig" to 80,"migration.signed.bin" to MAX_IMAGE,"main.signed.bin" to MAX_IMAGE)
    internal fun bounded(input:InputStream,limit:Int):ByteArray {
        val out=ByteArrayOutputStream(); val buffer=ByteArray(8192)
        while(true) {
            val n=input.read(buffer)
            if(n<0) break
            if(n==0) { val one=input.read(); if(one<0) break; require(out.size()<limit) {"Stream limit exceeded"}; out.write(one); continue }
            require(n<=limit-out.size()) {"Stream limit exceeded"}; out.write(buffer,0,n)
        }
        return out.toByteArray()
    }
    internal fun entries(input:InputStream,common:Boolean=false):Pair<Map<String,ByteArray>,String> {
        val allowed=if(common) limits+mapOf("recovery.signed.bin" to MAX_IMAGE,"main.ota" to ZigbeeCarrierValidator.MAX_CARRIER,
            "loader.bin" to 0xc000,"first-install.json" to 65536,"first-install.sig" to 80,"stock-restore.signed.bin" to 0x3f000,"stock-bootstrap.signed.bin" to 0xa2000) else limits
        val bytes=bounded(input,MAX_ZIP)
        val entries=linkedMapOf<String,ByteArray>(); var total=0
        ZipFile.builder().setSeekableByteChannel(SeekableInMemoryByteChannel(bytes)).get().use { zip ->
            val all=zip.entries
            while(all.hasMoreElements()) {
                val entry=all.nextElement(); val limit=allowed[entry.name] ?: error("Unexpected ZIP entry")
                require(!entry.isDirectory && !entry.isUnixSymlink && (entry.unixMode==0 || entry.unixMode and 0xf000==0x8000)) {"Nonregular entry"}
                require(entry.name !in entries && !entry.generalPurposeBit.usesEncryption()) {"Duplicate or encrypted entry"}
                require(zip.canReadEntryData(entry)) {"Unsupported ZIP entry"}
                val data=zip.getInputStream(entry).use { bounded(it,minOf(limit,MAX_ZIP-total)) }
                require(data.isNotEmpty()) {"Empty entry"}
                require(entry.size==data.size.toLong()) {"Truncated ZIP entry"}
                val crc=java.util.zip.CRC32().apply { update(data) }.value
                require(crc==entry.crc) {"ZIP CRC mismatch"}
                entries[entry.name]=data; total+=data.size
            }
        }
        return entries to sha256(bytes)
    }
    fun read(input:InputStream):RawPackage {
        val (entries,digest)=entries(input)
        require(entries.keys==limits.keys) {"Missing ZIP entry"}
        return RawPackage(entries.getValue("manifest.json"),entries.getValue("manifest.sig"),entries.getValue("migration.signed.bin"),entries.getValue("main.signed.bin"),digest)
    }
}
