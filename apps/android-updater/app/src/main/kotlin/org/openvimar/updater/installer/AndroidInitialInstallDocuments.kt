package org.openvimar.updater.installer

import android.content.ContentResolver
import android.net.Uri
import org.openvimar.installer.ArchiveExport
import java.io.IOException

/** Only an explicit ACTION_CREATE_DOCUMENT result is supplied by the UI. No
 * cloud/backup provider is chosen automatically and no private file URI leaks. */
internal object AndroidInitialInstallDocuments {
    fun reopenExisting(resolver:ContentResolver,uri:Uri,cancelled:()->Boolean):ByteArray{
        require(uri.scheme=="content"&&uri.authority?.isNotBlank()==true)
        return (resolver.openInputStream(uri)?:throw IOException("Selected original cannot be opened")).use{input->
            val out=java.io.ByteArrayOutputStream();val buffer=ByteArray(8192)
            while(true){if(cancelled())throw IOException("Original copy inspection cancelled");val n=input.read(buffer);if(n<0)break
                require(n>0&&out.size()+n<=SelectedDocumentExport.MAX){"Selected original exceeds bound"};out.write(buffer,0,n)}
            out.toByteArray()
        }
    }
    fun export(resolver:ContentResolver,uri:Uri,cancelled:()->Boolean):ArchiveExport {
        require(uri.scheme=="content"&&uri.authority?.isNotBlank()==true)
        return SelectedDocumentExport(uri.toString(),
            {resolver.openOutputStream(uri,"wt")?:throw IOException("Selected document could not be opened for export")},
            {resolver.openInputStream(uri)?:throw IOException("The same selected document could not be reopened")},
            {if(cancelled())throw IOException("Explicit document export cancelled")})
    }
}
