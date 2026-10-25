package org.openvimar.updater

import java.io.*
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import java.util.UUID

/** Read-only metadata, never an installation/fleet or approval capability. */
internal data class BenchCandidateRef(val digest:String,val familySha256:String,val cachePath:String)

/** Separate candidate namespace. Validation precedes exact-byte publication;
 * storing/reopening a candidate never remembers owner authorization. */
internal class BenchCandidateCache(private val directory:File,private val maxBytes:Int,
    private val inspect:(ByteArray)->BenchCandidateRef) {
    private val hashPattern=Regex("[0-9a-f]{64}")
    @Synchronized fun import(input:InputStream,checkActive:()->Unit={},progress:(Long)->Unit={}):BenchCandidateRef {
        require(maxBytes>0);check(directory.mkdirs()||directory.isDirectory)
        val temporary=File(directory,"candidate-${UUID.randomUUID()}.tmp")
        try {
            val bytes=input.use{bounded(it,maxBytes,checkActive,progress)}
            checkActive();val metadata=inspect(bytes.copyOf());checkActive()
            require(hashPattern.matches(metadata.digest)&&hashPattern.matches(metadata.familySha256)&&digest(bytes)==metadata.digest){"Inspected candidate differs from exact input"}
            FileOutputStream(temporary).use{output->checkActive();output.write(bytes);output.fd.sync()}
            checkActive();val destination=File(directory,"${metadata.digest}.zip")
            if(destination.exists())require(digest(readFile(destination,checkActive))==metadata.digest){"Cached candidate bytes changed"}
            else Files.move(temporary.toPath(),destination.toPath(),StandardCopyOption.ATOMIC_MOVE)
            return metadata.copy(cachePath=destination.canonicalPath)
        } finally {temporary.delete()}
    }
    @Synchronized fun read(reference:BenchCandidateRef,checkActive:()->Unit={}):ByteArray {
        require(hashPattern.matches(reference.digest)&&hashPattern.matches(reference.familySha256)){"Malformed candidate reference"}
        val file=File(directory,"${reference.digest}.zip")
        require(file.canonicalPath==File(reference.cachePath).canonicalPath&&file.canonicalFile.parentFile==directory.canonicalFile){"Candidate reference leaves private cache"}
        val bytes=readFile(file,checkActive)
        require(digest(bytes)==reference.digest){"Cached candidate digest changed"}
        return bytes
    }
    private fun readFile(file:File,checkActive:()->Unit):ByteArray {
        require(file.isFile&&file.length() in 1..maxBytes.toLong()){"Candidate cache size invalid"}
        return file.inputStream().use{bounded(it,maxBytes,checkActive,{})}
    }
    private fun bounded(input:InputStream,limit:Int,checkActive:()->Unit,progress:(Long)->Unit):ByteArray {
        val output=ByteArrayOutputStream();val buffer=ByteArray(8192)
        while(true) {
            checkActive();val count=input.read(buffer);checkActive();if(count<0)break
            if(count==0){val one=input.read();checkActive();if(one<0)break;require(output.size()<limit){"Candidate exceeds supported ZIP limit"};output.write(one)}
            else{require(count<=limit-output.size()){"Candidate exceeds supported ZIP limit"};output.write(buffer,0,count)}
            progress(output.size().toLong())
        }
        require(output.size()>0){"Empty candidate"};return output.toByteArray()
    }
    private fun digest(bytes:ByteArray)=MessageDigest.getInstance("SHA-256").digest(bytes).joinToString(""){"%02x".format(it.toInt() and 255)}
}
