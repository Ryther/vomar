package org.openvimar.updater.core

import org.junit.Assert.*
import org.junit.Test
import java.io.*
import java.security.*
import java.security.spec.X509EncodedKeySpec
import org.apache.commons.compress.archivers.zip.*

class PackageTest {
    private val fixture = File("../test-fixtures")
    private fun raw() = PackageReader.read(File(fixture,"synthetic-update.zip").inputStream())
    private fun key() = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(File(fixture,"synthetic-public.der").readBytes()))
    private fun rejects(block:()->Unit) { assertThrows(Exception::class.java, block) }
    @Test fun validatesPythonFixture() {
        val p = PackageValidator.validate(raw(),key(),"0.1.0")
        assertEquals("0.5.8", p.manifest.main.version)
        assertNotEquals(p.manifest.main.fileSha256,p.manifest.main.signedRegionSha256)
    }
    @Test fun rejectsTamperedManifestOrImage() {
        val r = raw()
        rejects { PackageValidator.validate(r.copy(manifest=r.manifest + 32.toByte()),key(),"0.1.0") }
        rejects { PackageValidator.validate(r.copy(main=r.main.copyOf().apply { this[40]=(this[40].toInt() xor 1).toByte() }),key(),"0.1.0") }
    }
    @Test fun rejectsWrongPublicKey() {
        val g=KeyPairGenerator.getInstance("EC"); g.initialize(256)
        rejects { PackageValidator.validate(raw(),g.generateKeyPair().public,"0.1.0") }
    }
    @Test fun enforcesActualStreamLimits() {
        rejects { PackageReader.read(object:InputStream(){ var n=0; override fun read()=if(n++<2097153) 0 else -1 }) }
        rejects { PackageReader.read(zip(listOf("manifest.json" to ByteArray(65537)))) }
        rejects { PackageReader.read(zip(listOf("manifest.sig" to ByteArray(81)))) }
        rejects { PackageReader.read(zip(listOf("main.signed.bin" to ByteArray(0xa4001)))) }
    }
    private fun zip(entries:List<Pair<String,ByteArray>>,symlink:Boolean=false):InputStream {
        val bytes=ByteArrayOutputStream()
        ZipArchiveOutputStream(bytes).use { out -> entries.forEach { (name,data) ->
            val entry=ZipArchiveEntry(name); entry.unixMode=if(symlink) 0xa1ff else 0x81a4
            out.putArchiveEntry(entry); out.write(data); out.closeArchiveEntry()
        }}
        return bytes.toByteArray().inputStream()
    }
    @Test fun rejectsExtraDuplicateTraversalSymlinkEntries() {
        listOf(listOf("extra" to byteArrayOf()),listOf("../manifest.json" to byteArrayOf()),
            listOf("manifest.json" to raw().manifest,"manifest.json" to raw().manifest)).forEach { entries ->
            if (entries.size == 2) {
                val error = assertThrows(IllegalArgumentException::class.java) { PackageReader.read(zip(entries)) }
                assertEquals("Duplicate or encrypted entry", error.message)
            } else rejects { PackageReader.read(zip(entries)) }
        }
        rejects { PackageReader.read(zip(listOf("manifest.json" to byteArrayOf()),true)) }
    }
    @Test fun rejectsTruncatedHeaderAndSignedRegion() {
        rejects { PackageValidator.signedRegionHash(ByteArray(31)) }
        val bytes=raw().main
        rejects { PackageValidator.signedRegionHash(bytes.copyOf(33)) }
    }
    @Test fun enforcesExpandedLimitsWithCompleteCompressedArchives() {
        val r=raw()
        val entries=listOf("manifest.json" to r.manifest,"manifest.sig" to r.signature,
            "migration.signed.bin" to r.migration,"main.signed.bin" to ByteArray(0xa4001))
        val error=assertThrows(IllegalArgumentException::class.java) { PackageReader.read(zip(entries)) }
        assertEquals("Stream limit exceeded",error.message)
    }
    @Test fun checksSymlinkAttributesInCentralDirectory() {
        val r=raw()
        val entries=listOf("manifest.json" to r.manifest,"manifest.sig" to r.signature,
            "migration.signed.bin" to r.migration,"main.signed.bin" to r.main)
        val error=assertThrows(IllegalArgumentException::class.java) { PackageReader.read(zip(entries,true)) }
        assertEquals("Nonregular entry",error.message)
    }
    @Test fun rejectsSignedUnknownFieldsAndWrongMetadata() {
        val r=raw()
        val g=KeyPairGenerator.getInstance("EC"); g.initialize(256); val pair=g.generateKeyPair()
        fun signed(text:String):RawPackage {
            val bytes=text.toByteArray()
            val sig=Signature.getInstance("SHA256withECDSA").apply { initSign(pair.private); update(bytes) }.sign()
            return r.copy(manifest=bytes,signature=sig)
        }
        val original=r.manifest.toString(Charsets.UTF_8)
        rejects { PackageValidator.validate(signed(original.replace("\"schemaVersion\":1","\"schemaVersion\":1,\"unknown\":true")),pair.public,"0.1.0") }
        val withoutId = original.replace("[0,5,8,0]", "[0,5,9,0]")
            .replace(Regex("\"bundleId\":\"[0-9a-f]{64}\","), "")
        val identifier = sha256(withoutId.toByteArray())
        val wrongVersion = signed(withoutId.replace("\"device\":", "\"bundleId\":\"$identifier\",\"device\":"))
        val versionError = assertThrows(IllegalArgumentException::class.java) {
            PackageValidator.validate(wrongVersion, pair.public, "0.1.0")
        }
        assertEquals("Wire version mismatch", versionError.message)
        rejects { PackageValidator.validate(signed(original.replace(Regex("\"bundleId\":\"[0-9a-f]{64}\""), "\"bundleId\":\""+"0".repeat(64)+"\"")),pair.public,"0.1.0") }
    }
    @Test fun rejectsNonordinaryImageFlags() {
        val bytes=raw().main.copyOf()
        bytes[16]=1
        rejects { PackageValidator.signedRegionHash(bytes) }
    }
    @Test fun validatesPythonAsciiCanonicalUnicodeName() {
        val r=raw()
        val g=KeyPairGenerator.getInstance("EC"); g.initialize(256); val pair=g.generateKeyPair()
        // Python ensure_ascii=True, sort_keys=True, compact separators.
        val name="\\u00abBagno \\u00e8 acceso \\ud83d\\udca1\\u00bb"
        val withoutId=r.manifest.toString(Charsets.UTF_8)
            .replace("Synthetic dimmer",name)
            .replace(Regex("\"bundleId\":\"[0-9a-f]{64}\","),"")
        val identifier=sha256(withoutId.toByteArray())
        val text=withoutId.replace("\"device\":","\"bundleId\":\""+identifier+"\",\"device\":")
        val bytes=text.toByteArray()
        val signature=Signature.getInstance("SHA256withECDSA").apply { initSign(pair.private); update(bytes) }.sign()
        val validated=PackageValidator.validate(r.copy(manifest=bytes,signature=signature),pair.public,"0.1.0")
        assertEquals("«Bagno è acceso 💡»",validated.manifest.device.name)
    }
    @Test fun requiresCompatibleAppVersion() {
        rejects { PackageValidator.validate(raw(),key(),"0.0.9") }
    }
}
