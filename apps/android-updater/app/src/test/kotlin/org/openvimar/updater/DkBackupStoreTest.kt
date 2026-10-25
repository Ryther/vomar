package org.openvimar.updater

import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.time.Instant
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

class DkBackupStoreTest {
    private fun archive(): ByteArray=ByteArrayOutputStream().also {output->ZipOutputStream(output).use {zip->
        zip.putNextEntry(ZipEntry("synthetic-test-entry"));zip.write(byteArrayOf(1,2,3));zip.closeEntry()
    }}.toByteArray()
    @Test fun publishesWithoutOverwriteAndNeverOffersPartialFiles() {
        val directory=Files.createTempDirectory("dk-backup-store").toFile()
        try {
            val store=DkBackupStore(directory);val bytes=archive()
            File(directory,"capture-interrupted.partial").writeBytes(bytes.copyOf(10))
            assertNull(store.latest())
            store.cleanupIncomplete();assertTrue(directory.listFiles().orEmpty().isEmpty())
            val target=store.publish(bytes,DkBackupIdentity(1,2,0x52840),Instant.ofEpochMilli(1000))
            assertArrayEquals(bytes,target.readBytes())
            assertEquals(target,store.latest())
            try {store.publish(bytes,DkBackupIdentity(1,2,0x52840),Instant.ofEpochMilli(1000));fail("Overwritten")}
            catch(_: IOException) {assertArrayEquals(bytes,target.readBytes())}
            assertNull(store.resolveVerified("../capture-interrupted.partial"))
            assertEquals(1,directory.listFiles().orEmpty().size)
        } finally {directory.deleteRecursively()}
    }
    @Test fun cancellationAndInvalidInputLeaveNoExportableFile() {
        val directory=Files.createTempDirectory("dk-backup-cancel").toFile()
        try {
            val store=DkBackupStore(directory)
            for(bytes in listOf(byteArrayOf(),archive())) {
                try {store.publish(bytes,DkBackupIdentity(1,2,0x52840),Instant.ofEpochMilli(1000),cancelled={true});fail("Published cancelled data")}
                catch(_: IOException) {assertNull(store.latest())}
            }
            assertTrue(directory.listFiles().orEmpty().isEmpty())
        } finally {directory.deleteRecursively()}
    }
    @Test fun corruptedPublishedBytesAreNotOfferedForExportAfterReopen() {
        val directory=Files.createTempDirectory("dk-backup-corrupt").toFile()
        try {
            val store=DkBackupStore(directory)
            val file=store.publish(archive(),DkBackupIdentity(1,2,0x52840),Instant.ofEpochMilli(1000))
            file.writeBytes(file.readBytes().dropLast(2).toByteArray())
            assertNull(DkBackupStore(directory).resolveVerified(file.name))
            assertNull(DkBackupStore(directory).latest())
        } finally {directory.deleteRecursively()}
    }
}
