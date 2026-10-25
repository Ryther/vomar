package org.openvimar.updater

import java.io.*
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import java.util.UUID

/** Copy a bounded candidate, authenticate it, then atomically publish exact bytes. */
internal class FleetReleaseCache(private val directory:File,private val maxBytes:Int,
    private val validator:(File)->FleetReleaseRef) {
    @Synchronized fun import(input:InputStream,checkActive:()->Unit={},progress:(Long)->Unit={}):FleetReleaseRef {
        directory.mkdirs();val candidate=File(directory,"candidate-${UUID.randomUUID()}.tmp")
        try {
            val digest=MessageDigest.getInstance("SHA-256");var total=0L
            input.use{source->FileOutputStream(candidate).use{out->val buffer=ByteArray(8192)
                while(true){checkActive();val count=source.read(buffer);checkActive();if(count<0)break
                    require(count<=maxBytes-total){"Release exceeds the supported ZIP limit"};out.write(buffer,0,count);digest.update(buffer,0,count);total+=count;progress(total)}
                out.fd.sync()
            }}
            checkActive();val measured=digest.digest().joinToString(""){"%02x".format(it.toInt() and 255)}
            val validated=validator(candidate);require(validated.digest==measured){"Verified release digest differs from downloaded bytes"};checkActive()
            val destination=File(directory,"$measured.zip")
            if(destination.exists())require(hash(destination)==measured){"Cached release bytes changed"}
            else Files.move(candidate.toPath(),destination.toPath(),StandardCopyOption.ATOMIC_MOVE)
            return validated.copy(cachePath=destination.canonicalPath)
        } finally {candidate.delete()}
    }
    fun file(ref:FleetReleaseRef):File {
        require(Regex("[0-9a-f]{64}").matches(ref.digest))
        val file=File(directory,"${ref.digest}.zip")
        require(file.canonicalPath==File(ref.cachePath).canonicalPath&&file.canonicalFile.parentFile==directory.canonicalFile&&file.length() in 1..maxBytes.toLong()){"Release cache reference invalid"}
        require(hash(file)==ref.digest){"Cached release digest changed"};return file
    }
    private fun hash(file:File):String {
        val digest=MessageDigest.getInstance("SHA-256");file.inputStream().use{input->val buffer=ByteArray(8192);while(true){val n=input.read(buffer);if(n<0)break;digest.update(buffer,0,n)}}
        return digest.digest().joinToString(""){"%02x".format(it.toInt() and 255)}
    }
}
