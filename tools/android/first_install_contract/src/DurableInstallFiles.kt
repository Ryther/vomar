package org.openvimar.installer

import java.nio.channels.FileChannel
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.Path
import java.nio.file.StandardOpenOption

/** App-private namespace publication, not SAF/provider durability. A synced
 * file is insufficient if a newly created ancestor entry can still vanish.
 * API26 NIO only; every IO/sync error must block mutation admission. */
object DurableInstallFiles {
    fun syncDirectory(directory:Path){
        require(Files.isDirectory(directory,LinkOption.NOFOLLOW_LINKS)){"Private evidence directory is invalid"}
        FileChannel.open(directory,StandardOpenOption.READ).use{it.force(true)}
    }
    fun ensureDirectory(directory:Path)=ensureDirectory(directory,::syncDirectory)
    /** Internal syscall seam executes the same creation/order logic in tests;
     * production callers cannot replace the sync implementation. */
    internal fun ensureDirectory(directory:Path,sync:(Path)->Unit){
        val absolute=directory.toAbsolutePath().normalize()
        if(!Files.exists(absolute,LinkOption.NOFOLLOW_LINKS)){
            val parent=requireNotNull(absolute.parent);ensureDirectory(parent,sync)
            Files.createDirectory(absolute)
        }
        require(Files.isDirectory(absolute,LinkOption.NOFOLLOW_LINKS)){"Private evidence path is not a directory"}
        sync(absolute);absolute.parent?.let(sync)
    }
}
