package org.openvimar.updater

import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.nio.file.Files
import java.time.Instant
import java.util.Locale

/** Private publication boundary. Only a complete verified in-memory ZIP is
 * accepted by the service; a temporary file is never selectable for export. */
internal class DkBackupStore(private val directory: File) {
    private val pattern=Regex("backup-[0-9a-f]{8}-[0-9a-f]{8}-[0-9]+-([0-9a-f]{64})\\.verified\\.zip")
    init { if(!directory.isDirectory&&!directory.mkdirs())throw IOException("Cannot open private backup storage") }
    fun cleanupIncomplete() { directory.listFiles()?.filter {it.name.endsWith(".partial")}?.forEach {it.delete()} }
    fun resolveVerified(name: String): File? {
        val match=pattern.matchEntire(name) ?: return null
        val file=File(directory,name)
        return file.takeIf {it.isFile&&it.length() in 1..0x120000&&runCatching {
            DkBackupArchive.sha256(it.readBytes())==match.groupValues[1]
        }.getOrDefault(false)}
    }
    fun latest(): File? = directory.listFiles()?.filter {resolveVerified(it.name)!=null}?.maxByOrNull {it.lastModified()}
    fun publish(archive: ByteArray,identity: DkBackupIdentity,verifiedAt: Instant,cancelled: () -> Boolean = {false}): File {
        if(archive.size<4 || !archive.copyOfRange(0,4).contentEquals(byteArrayOf(0x50,0x4b,3,4)))throw IOException("Verified ZIP is missing")
        val digest=DkBackupArchive.sha256(archive)
        val name=String.format(Locale.ROOT,"backup-%08x-%08x-%d-%s.verified.zip",identity.uid0,identity.uid1,verifiedAt.toEpochMilli(),digest)
        if(!pattern.matches(name))throw IOException("Invalid private backup filename")
        val target=File(directory,name)
        if(target.exists())throw IOException("Existing verified backups cannot be overwritten")
        val partial=File.createTempFile("capture-",".partial",directory)
        try {
            if(cancelled())throw IOException("Backup cancelled before publication")
            FileOutputStream(partial).use {output->output.write(archive);output.fd.sync()}
            if(partial.length()!=archive.size.toLong() || DkBackupArchive.sha256(partial.readBytes())!=DkBackupArchive.sha256(archive))
                throw IOException("Private backup write did not verify")
            if(cancelled())throw IOException("Backup cancelled before publication")
            Files.move(partial.toPath(),target.toPath()) // No REPLACE_EXISTING.
            return target
        } finally {partial.delete()}
    }
}
