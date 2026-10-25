package org.openvimar.updater

import java.io.IOException
import java.io.ByteArrayOutputStream
import java.security.MessageDigest
import java.time.Instant
import java.util.Locale
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

internal enum class DkBackupRegion(val start: Long,val size: Int,val fileName: String) {
    FLASH(0,0x100000,"flash.bin"), FICR(0x10000000,4096,"ficr.bin"), UICR(0x10001000,4096,"uicr.bin")
}
internal data class DkBackupIdentity(val uid0: Long,val uid1: Long,val part: Long)
internal data class DkBackupPass(val identityBefore: DkBackupIdentity,val identityAfter: DkBackupIdentity,
    val regions: Map<DkBackupRegion,ByteArray>)
internal data class DkBackupProvenance(val appVersion: String,val probeFirmware: String,val targetMillivolts: Int,
    val usbVendorId: Int,val usbProductId: Int,val interfaceId: Int,val inputEndpoint: Int,val outputEndpoint: Int,
    val startedAt: Instant,val verifiedAt: Instant)
internal data class DkKnownStockApplication(val id: String,val model: String,val radio: String,
    val offset: Int,val size: Int,val sha256: String)
internal object DkBackupArchive {
    fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes)
        .joinToString("") { String.format(Locale.ROOT,"%02x",it.toInt() and 255) }
    private fun word(bytes: ByteArray,offset: Int): Long = (0..3).fold(0L) { value,index ->
        value or ((bytes[offset+index].toLong() and 255) shl (index*8))
    }
    private fun hex(value: Long) = String.format(Locale.ROOT,"0x%08x",value)
    private fun reject(message: String): Nothing = throw IOException(message)
    private fun json(value: Any?): String = when(value) {
        null -> "null"
        is String -> "\""+buildString { for(char in value) append(when(char) {
            '"' -> "\\\""; '\\' -> "\\\\"; '\n' -> "\\n"; '\r' -> "\\r"; '\t' -> "\\t"
            else -> if(char.code<32) String.format(Locale.ROOT,"\\u%04x",char.code) else char.toString()
        }) }+"\""
        is Number,is Boolean -> value.toString()
        is Map<*,*> -> value.entries.joinToString(",","{","}") { json(it.key.toString())+":"+json(it.value) }
        is Iterable<*> -> value.joinToString(",","[","]") { json(it) }
        else -> reject("Unsupported backup metadata")
    }

    /** Freeze and validate all bytes BEFORE opening a ZIP writer. Two matching
     * running-target reads prove repeatability, not an atomic snapshot. */
    fun create(first: DkBackupPass,second: DkBackupPass,identity: DkBackupIdentity,provenance: DkBackupProvenance,
        known: List<DkKnownStockApplication> = DkPublicStockApplications.entries): ByteArray {
        if (identity.part!=0x52840L || identity.uid0 !in 0..0xffffffffL || identity.uid1 !in 0..0xffffffffL ||
            listOf(first.identityBefore,first.identityAfter,second.identityBefore,second.identityAfter).any { it!=identity })
            reject("Live target identity changed or is unsupported")
        if (provenance.appVersion.isBlank() || provenance.appVersion.length>128 || provenance.probeFirmware.isBlank() ||
            provenance.probeFirmware.length>1024 || provenance.targetMillivolts !in 1700..3600 ||
            provenance.usbVendorId!=0x1366 || provenance.usbProductId!=0x1060 || provenance.interfaceId<0 ||
            provenance.inputEndpoint !in 0x81..0x8f || provenance.outputEndpoint !in 1..15 ||
            provenance.verifiedAt.isBefore(provenance.startedAt)) reject("Invalid backup provenance")
        val required=DkBackupRegion.entries.toSet()
        if(first.regions.keys!=required || second.regions.keys!=required) reject("Backup is missing a required region")
        val frozen=linkedMapOf<DkBackupRegion,ByteArray>()
        for(region in DkBackupRegion.entries) {
            if(first.regions.getValue(region)===second.regions.getValue(region))reject("Two independent acquisition buffers are required")
            val a=first.regions.getValue(region).copyOf();val b=second.regions.getValue(region).copyOf()
            if(a.size!=region.size || b.size!=region.size || !a.contentEquals(b))
                reject("${region.name} double read is incomplete or differs")
            frozen[region]=a
        }
        val ficr=frozen.getValue(DkBackupRegion.FICR)
        // Nordic nRF52840 FICR: INFO.RAM/FLASH at10c/110 encode kB.
        // https://docs.nordicsemi.com/r/bundle/ps_nrf52840/page/ficr.html
        if(word(ficr,0x60)!=identity.uid0 || word(ficr,0x64)!=identity.uid1 || word(ficr,0x100)!=identity.part ||
            word(ficr,0x10)!=4096L || word(ficr,0x14)!=256L || word(ficr,0x10c)!=256L || word(ficr,0x110)!=1024L)
            reject("FICR dump does not match live UID/PART or nRF52840 geometry")
        val flash=frozen.getValue(DkBackupRegion.FLASH)
        val stack=word(flash,0);val reset=word(flash,4)
        if(stack<=0x20000000 || stack>0x20040000 || stack%8!=0L || reset and 1==0L ||
            (reset and 0xfffffffeL)<8 || (reset and 0xfffffffeL)>=0x100000) reject("FLASH initial vectors are not plausible")
        if(known.size>64 || known.map { it.id }.toSet().size!=known.size || known.any {
            it.id.isBlank() || it.model.isBlank() || it.offset<0 || it.size<=0 ||
                it.offset.toLong()+it.size>flash.size || !it.sha256.matches(Regex("[0-9a-f]{64}")) })
            reject("Invalid stock application fingerprint registry")
        val recognized=known.filter { sha256(flash.copyOfRange(it.offset,it.offset+it.size))==it.sha256 }
        val target=linkedMapOf<String,Any>("chip" to "nRF52840", "part" to hex(identity.part),
            "uid" to listOf(hex(identity.uid0),hex(identity.uid1)),"identitySource" to "live FICR before/after both passes",
            "commercialModelVerified" to false,
            "model" to if(recognized.isEmpty()) "unknown nRF52840 device" else "stock application recognized; hardware model unverified")
        if(recognized.isNotEmpty()) {
            target["applicationDigestMatched"]=true
            target["firmwareModel"]=recognized.map { it.model }.distinct().joinToString(",")
            target["recognizedApplications"]=recognized.map { mapOf("id" to it.id,"model" to it.model,"radio" to it.radio,
                "offset" to it.offset,"size" to it.size,"sha256" to it.sha256) }
        }
        val manifest=linkedMapOf<String,Any>("schema" to 1,"type" to "nrf52840-read-only-double-backup",
            "target" to target,"byteExactDoubleRead" to true,"startedAt" to provenance.startedAt.toString(),
            "verifiedAt" to provenance.verifiedAt.toString(),"snapshotAtomic" to false,
            "protocol" to mapOf("id" to "jlink-raw-swd-ap0-read-v1","swdClockKhz" to 100,
                "maxBlockBytes" to 512,"tarBoundaryBytes" to 1024,"independentBlockSentinels" to true),
            "scope" to mapOf("haltAttempted" to false,"resetAttempted" to false,"eraseAttempted" to false,
                "memoryWrite" to false,"flashed" to false,"targetSupplyChanged" to false,
                "debugPortConfigured" to true,"restorationVerified" to false),
            "provenance" to mapOf("appVersion" to provenance.appVersion,"probeFirmware" to provenance.probeFirmware,
                "usbVendorId" to provenance.usbVendorId,"usbProductId" to provenance.usbProductId,
                "interfaceId" to provenance.interfaceId,"inputEndpoint" to provenance.inputEndpoint,
                "outputEndpoint" to provenance.outputEndpoint,"targetMillivolts" to provenance.targetMillivolts),
            "regions" to frozen.map { (region,bytes) -> mapOf("file" to region.fileName,"start" to hex(region.start),
                "size" to bytes.size,"sha256" to sha256(bytes),"verifiedCopies" to 2) })
        val output=ByteArrayOutputStream()
        ZipOutputStream(output).use { zip ->
            fun entry(name: String,bytes: ByteArray) { zip.putNextEntry(ZipEntry(name).apply { time=0 });zip.write(bytes);zip.closeEntry() }
            for((region,bytes) in frozen) entry(region.fileName,bytes)
            entry("manifest.json",(json(manifest)+"\n").toByteArray(Charsets.UTF_8))
            entry("README.txt",("Private nRF52840 backup: keep this archive private. It contains chip identity, configuration and potentially network credentials.\n"+
                "FLASH, FICR and UICR were read twice and compared byte for byte. Live identity and dump geometry were checked.\n"+
                "The CPU was not halted or reset; two matching reads do not prove an atomic snapshot of a running device.\n"+
                "No erase, programming, unlock, target-supply change or restoration test was performed.\n"+
                "An application digest match identifies firmware bytes, not the commercial hardware model.\n").toByteArray(Charsets.UTF_8))
        }
        return output.toByteArray()
    }
}

/** Public immutable-input hashes only; no vendor bytes or per-unit IDs.
 * Source: experiments/android-backup-public-fingerprints-20261023/stock-application-hashes.json. */
internal object DkPublicStockApplications {
    val entries=listOf(
        DkKnownStockApplication("vimar-30805-mesh","VIMAR30805","mesh",0x26000,213012,
            "8c0408c49fe3e35758a69e511faa154c2f1237512e1c1bfdf1061221db53f927"),
        DkKnownStockApplication("vimar-30805-zigbee","VIMAR30805","zigbee",0x26000,343988,
            "710f788a02eca3985d5826efacf47cef8d8fa29dde4684815c25c8c9a79690d5"))
}
