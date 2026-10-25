package org.openvimar.updater.installer

import org.openvimar.installer.ArchiveExport
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.io.OutputStream

/** The document was selected explicitly by the user. Completion includes close;
 * the canonical engine then independently validates/compares its exact reopen. */
internal class SelectedDocumentExport(private val document:String,private val output:()->OutputStream,
    private val input:()->InputStream,private val checkCancelled:()->Unit={}):ArchiveExport {
    override fun create(bytes:ByteArray):String {
        require(document.isNotBlank()&&document.length<=4096&&bytes.size in 22..MAX)
        output().use{stream->var at=0;while(at<bytes.size){checkCancelled();val n=minOf(8192,bytes.size-at);stream.write(bytes,at,n);at+=n};checkCancelled();stream.flush()}
        checkCancelled();return document
    }
    override fun reopen(document:String):ByteArray {
        require(document==this.document){"Export document changed"}
        val out=ByteArrayOutputStream();input().use{stream->val buffer=ByteArray(8192)
            while(true){checkCancelled();val n=stream.read(buffer);if(n<0)break;require(n>0&&out.size()+n<=MAX){"Invalid/oversized reopened backup"};out.write(buffer,0,n)}}
        checkCancelled();return out.toByteArray()
    }
    companion object {const val MAX=2*1024*1024}
}
