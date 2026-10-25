package org.openvimar.updater

import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.IOException
import java.time.Instant
import java.util.zip.ZipInputStream

class DkBackupArchiveTest {
    private val identity = DkBackupIdentity(0x12345678,0xabcdef01,0x52840)
    private val provenance = DkBackupProvenance("test", "J-Link test\n\"quoted\"", 3300,
        0x1366,0x1060,4,0x85,3,Instant.parse("2026-10-23T10:00:00Z"),Instant.parse("2026-10-23T10:05:00Z"))
    private fun put(bytes: ByteArray, offset: Int, value: Long) {
        repeat(4) { bytes[offset+it] = (value ushr (it*8)).toByte() }
    }
    private fun data(): MutableMap<DkBackupRegion, ByteArray> {
        val flash = ByteArray(0x100000) { 0xa5.toByte() }
        put(flash,0,0x20040000);put(flash,4,0x101)
        val ficr = ByteArray(4096) { 0xff.toByte() }
        put(ficr,0x10,4096);put(ficr,0x14,256);put(ficr,0x60,0x12345678)
        put(ficr,0x64,0xabcdef01);put(ficr,0x100,0x52840);put(ficr,0x10c,256);put(ficr,0x110,1024)
        return mutableMapOf(DkBackupRegion.FLASH to flash,DkBackupRegion.FICR to ficr,
            DkBackupRegion.UICR to ByteArray(4096) { 0xff.toByte() })
    }
    private fun pass(data: Map<DkBackupRegion,ByteArray>, after: DkBackupIdentity = identity) =
        DkBackupPass(identity,after,data.mapValues {it.value.copyOf()})
    private fun unpack(bytes: ByteArray): Map<String,ByteArray> = ZipInputStream(ByteArrayInputStream(bytes)).use { zip ->
        val result = linkedMapOf<String,ByteArray>()
        while (true) { val entry = zip.nextEntry ?: break; assertFalse(result.containsKey(entry.name));result[entry.name] = zip.readBytes() }
        result
    }
    private fun rejected(action: () -> Unit) {
        try { action();fail("Invalid backup must not produce an archive") } catch (_: IOException) { }
    }

    @Test fun returnsOneCompleteZipOnlyAfterDoubleReadIdentityAndGeometryChecks() {
        val first=data();val second=data()
        val archive=DkBackupArchive.create(pass(first),pass(second),identity,provenance)
        val entries=unpack(archive)
        assertEquals(setOf("flash.bin","ficr.bin","uicr.bin","manifest.json","README.txt"),entries.keys)
        for(region in DkBackupRegion.entries) assertArrayEquals(first[region],entries[region.fileName])
        val manifest=entries.getValue("manifest.json").toString(Charsets.UTF_8)
        assertTrue(manifest.contains("\"byteExactDoubleRead\":true"))
        assertTrue(manifest.contains("\"uid\":[\"0x12345678\",\"0xabcdef01\"]"))
        assertTrue(manifest.contains("\"model\":\"unknown nRF52840 device\""))
        assertTrue(manifest.contains("2026-10-23T10:05:00Z"))
        assertTrue(manifest.contains("J-Link test\\n\\\"quoted\\\""))
        assertTrue(manifest.contains("\"haltAttempted\":false"))
        assertTrue(manifest.contains("\"eraseAttempted\":false"))
        assertTrue(manifest.contains("\"size\":1048576"))
        assertTrue(manifest.contains(DkBackupArchive.sha256(first.getValue(DkBackupRegion.FLASH))))
    }

    @Test fun rejectsMissingShortOversizedOrDifferentCopiesInEveryRegion() {
        for(region in DkBackupRegion.entries) {
            val missing=data().also { it.remove(region) }
            rejected { DkBackupArchive.create(pass(missing),pass(data()),identity,provenance) }
            for(size in listOf(region.size-4,region.size+4)) {
                val wrong=data().also { it[region]=ByteArray(size) }
                rejected { DkBackupArchive.create(pass(wrong),pass(wrong),identity,provenance) }
            }
            val different=data().also { it.getValue(region)[20]=(it.getValue(region)[20].toInt() xor 1).toByte() }
            rejected { DkBackupArchive.create(pass(data()),pass(different),identity,provenance) }
        }
    }

    @Test fun rejectsWrongLiveUidPartGeometryAndUnstableIdentity() {
        for(offset in listOf(0x60,0x64,0x100,0x10,0x14,0x10c,0x110)) {
            val invalid=data().also { put(it.getValue(DkBackupRegion.FICR),offset,0) }
            rejected { DkBackupArchive.create(pass(invalid),pass(invalid),identity,provenance) }
        }
        val wrong=identity.copy(uid0=0x87654321)
        rejected { DkBackupArchive.create(pass(data(),wrong),pass(data()),identity,provenance) }
        rejected { DkBackupArchive.create(pass(data()),pass(data()),wrong,provenance) }
    }

    @Test fun rejectsImplausibleInitialVectors() {
        for((stack,reset) in listOf(0L to 0x101L,0x20040004L to 0x101L,
            0x20040000L to 0x100L,0x20040000L to 0x100001L,0x20040000L to 1L)) {
            val invalid=data().also { put(it.getValue(DkBackupRegion.FLASH),0,stack);put(it.getValue(DkBackupRegion.FLASH),4,reset) }
            rejected { DkBackupArchive.create(pass(invalid),pass(invalid),identity,provenance) }
        }
    }

    @Test fun recognizesOnlyAnExactApplicationSliceDigest() {
        val original=data()
        val app=byteArrayOf(1,2,3,4,5,6,7,8)
        app.copyInto(original.getValue(DkBackupRegion.FLASH),0x26000)
        val known=DkKnownStockApplication("synthetic-known-app","VIMAR30805","test",0x26000,8,DkBackupArchive.sha256(app))
        val entries=unpack(DkBackupArchive.create(pass(original),pass(original),identity,provenance,listOf(known)))
        val manifest=entries.getValue("manifest.json").toString(Charsets.UTF_8)
        assertTrue(manifest.contains("\"applicationDigestMatched\":true"))
        assertTrue(manifest.contains("\"firmwareModel\":\"VIMAR30805\""))
        assertTrue(manifest.contains("\"commercialModelVerified\":false"))
        val changed=original.mapValues { it.value.copyOf() }
        changed.getValue(DkBackupRegion.FLASH)[0x26000]=0
        val changedManifest=unpack(DkBackupArchive.create(pass(changed),pass(changed),identity,provenance,listOf(known)))
            .getValue("manifest.json").toString(Charsets.UTF_8)
        assertFalse(changedManifest.contains("\"applicationDigestMatched\":true"))
        assertTrue(changedManifest.contains("unknown nRF52840 device"))
    }

    @Test fun rejectsInvalidProvenanceBeforeAnyArchiveCanBeReturned() {
        for(invalid in listOf(provenance.copy(verifiedAt=provenance.startedAt.minusSeconds(1)),
            provenance.copy(targetMillivolts=0),provenance.copy(usbVendorId=0),provenance.copy(inputEndpoint=3)))
            rejected { DkBackupArchive.create(pass(data()),pass(data()),identity,invalid) }
    }
    @Test fun rejectsTheSameAcquisitionBufferPassedAsTwoCopies() {
        val same=DkBackupPass(identity,identity,data())
        rejected {DkBackupArchive.create(same,same,identity,provenance)}
    }
    @Test fun usesTheStandardSha256Digest() {
        assertEquals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            DkBackupArchive.sha256("abc".toByteArray()))
    }
}
