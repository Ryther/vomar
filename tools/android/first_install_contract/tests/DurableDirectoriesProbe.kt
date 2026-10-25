package org.openvimar.installer

import java.nio.file.Files
import java.nio.file.Path
import java.nio.channels.FileChannel
import java.nio.file.StandardOpenOption

internal fun durableDirectoriesProbe(root:Path){
 val owned=root.resolve("files/dk-first-install/originals");val events=mutableListOf<Path>()
 DurableInstallFiles.ensureDirectory(owned){path->check(Files.isDirectory(path));events.add(path);FileChannel.open(path,StandardOpenOption.READ).use{it.force(true)}}
 val parts=listOf(root.resolve("files"),root.resolve("files/dk-first-install"),owned)
 for(path in parts){check(path in events&&path.parent in events);check(events.indexOf(path.parent)<events.lastIndexOf(path))}
 val existing=mutableListOf<Path>();DurableInstallFiles.ensureDirectory(owned){existing.add(it)}
 check(existing==listOf(owned,owned.parent))
 val failed=root.resolve("failed/transactions")
 check(runCatching{DurableInstallFiles.ensureDirectory(failed){path->if(path==root)error("Parent fsync failed")}}.isFailure)
 check(!Files.exists(failed))
 val link=root.resolve("linked");Files.createSymbolicLink(link,owned)
 check(runCatching{DurableInstallFiles.ensureDirectory(link)}.isFailure)
}
