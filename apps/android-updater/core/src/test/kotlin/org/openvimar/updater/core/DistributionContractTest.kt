package org.openvimar.updater.core

import java.io.File
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.security.KeyFactory
import java.security.MessageDigest
import java.security.spec.X509EncodedKeySpec
import java.util.zip.ZipInputStream
import java.util.zip.ZipOutputStream
import java.util.zip.ZipEntry
import kotlinx.serialization.json.*
import org.junit.Test
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows

class DistributionContractTest {
    @Test fun sourceOwnedGoldenPackages() {
        val root=File(requireNotNull(System.getProperty("vomar.root")))
        val cases=Json.parseToJsonElement(File(root,"tests/contracts/packages.json").readText()).jsonObject.getValue("cases").jsonArray
        cases.forEach { entry ->
            val c=entry.jsonObject;val id=c.getValue("id").jsonPrimitive.content
            var bytes=File(root,c.getValue("path").jsonPrimitive.content).readBytes()
            assertEquals(id,c.getValue("sourceSha256").jsonPrimitive.content,MessageDigest.getInstance("SHA-256").digest(bytes).joinToString(""){"%02x".format(it.toInt() and 255)})
            when(c.getValue("mutation").jsonPrimitive.content) {
                "truncate" -> bytes=bytes.copyOf(bytes.size-10)
                "extra-entry" -> {
                    val out=ByteArrayOutputStream()
                    ZipOutputStream(out).use{z->ZipInputStream(ByteArrayInputStream(bytes)).use{input->while(true){val e=input.nextEntry ?: break;z.putNextEntry(ZipEntry(e.name));input.copyTo(z);z.closeEntry()}};z.putNextEntry(ZipEntry("extra.txt"));z.write("{}".toByteArray());z.closeEntry()}
                    bytes=out.toByteArray()
                }

            }
            val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(File(root,c.getValue("publicKey").jsonPrimitive.content).readBytes()))
            val accepted=runCatching {
                if(c.getValue("schema").jsonPrimitive.int==1)PackageValidator.validate(PackageReader.read(ByteArrayInputStream(bytes)),key,"1.0.0")
                else CommonPackageValidator.validate(CommonPackageReader.read(ByteArrayInputStream(bytes)),key,"1.0.0")
            }.isSuccess
            assertEquals(id,c.getValue("accept").jsonPrimitive.boolean,accepted)
        }
    }
    @Test fun sharedDistributionManifest() {
        val root=File(requireNotNull(System.getProperty("vomar.root")))
        val cases=Json.parseToJsonElement(File(root,"tests/contracts/distribution.json").readText()).jsonObject.getValue("cases").jsonArray
        cases.forEach { item ->
            val c=item.jsonObject
            assertEquals(c.getValue("id").jsonPrimitive.content,c.getValue("accept").jsonPrimitive.boolean,
                runCatching{DistributionAssets.parse(c.getValue("manifest").toString().toByteArray(),"v0.1.0")}.isSuccess)
        }
    }
    @Test fun distributionPreservesIndependentNativeComponentVersions() {
        val selected=DistributionAssets.parse(independentDistribution().toString().toByteArray(),"v2.0.0")
        assertEquals("v2.0.0",selected.tag)
        assertEquals("vomar-firmware-2.0.0.zip",selected.firmware.filename)
        assertEquals("vomar-zigbee-1.1.1.ota",selected.ota.filename)
        assertEquals("vomar-android-1.1.2.apk",selected.assets.single{it.role=="android-apk"}.filename)
        assertEquals("vomar-desktop-1.1.0-linux-x64.zip",selected.assets.single{it.role=="desktop-linux-x64"}.filename)
        assertEquals("vomar-converter-1.0.0.js",selected.assets.single{it.role=="zigbee2mqtt-converter"}.filename)
        assertEquals(11,selected.assets.size)
    }
    @Test fun distributionRequiresExactlyTheFourKnownComponentOwners() {
        val manifest=independentDistribution();val components=manifest.getValue("components").jsonObject
        for(owner in listOf("firmware","android","desktop","zigbee2mqtt")){
            val missing=JsonObject(manifest+("components" to JsonObject(components-owner)))
            assertThrows("Missing component owner $owner",IllegalArgumentException::class.java){
                DistributionAssets.parse(missing.toString().toByteArray(),"v2.0.0")
            }
        }
        for(extra in listOf("unknown","zigbee2mqtt-converter")){
            val expanded=JsonObject(manifest+("components" to JsonObject(components+(extra to JsonPrimitive("1.0.0")))))
            assertThrows("Unexpected component owner $extra",IllegalArgumentException::class.java){
                DistributionAssets.parse(expanded.toString().toByteArray(),"v2.0.0")
            }
        }
    }
    @Test fun everyNativeArtifactMustUseItsOwnersExactVersion() {
        for(role in listOf("firmware-common","zigbee-ota","android-apk","desktop-linux-x64",
            "desktop-windows-x64","desktop-windows-setup","desktop-macos-arm64","zigbee2mqtt-converter")){
            assertThrows("Wrong component version for $role",IllegalArgumentException::class.java){
                DistributionAssets.parse(withArtifactVersion(role,"9.9.9").toString().toByteArray(),"v2.0.0")
            }
        }
    }
    @Test fun sharedReleaseDocumentsAndSbomUseTheDistributionVersion() {
        for(role in listOf("licenses","offline-guide","source-sbom")){
            assertThrows("Distribution-owned artifact $role cannot claim the firmware version",IllegalArgumentException::class.java){
                DistributionAssets.parse(withArtifactVersion(role,"1.1.1").toString().toByteArray(),"v2.0.0")
            }
        }
    }
    private fun withArtifactVersion(role:String,version:String):JsonObject {
        val manifest=independentDistribution()
        val artifacts=manifest.getValue("artifacts").jsonArray.map{entry->
            val artifact=entry.jsonObject
            if(artifact.getValue("role").jsonPrimitive.content==role)JsonObject(artifact+("componentVersion" to JsonPrimitive(version))) else artifact
        }
        return JsonObject(manifest+("artifacts" to JsonArray(artifacts)))
    }
    private fun independentDistribution():JsonObject {
        val sha="ab".repeat(32)
        return Json.parseToJsonElement("""
            {
              "schemaVersion":1,"distributionVersion":"2.0.0","tag":"v2.0.0","commit":"${"a".repeat(40)}",
              "components":{"firmware":"1.1.1","android":"1.1.2","desktop":"1.1.0","zigbee2mqtt":"1.0.0"},
              "artifacts":[
                {"role":"firmware-common","filename":"vomar-firmware-2.0.0.zip","size":1,"sha256":"$sha","componentVersion":"1.1.1"},
                {"role":"zigbee-ota","filename":"vomar-zigbee-1.1.1.ota","size":1,"sha256":"$sha","componentVersion":"1.1.1"},
                {"role":"android-apk","filename":"vomar-android-1.1.2.apk","size":1,"sha256":"$sha","componentVersion":"1.1.2","androidVersionCode":32},
                {"role":"desktop-linux-x64","filename":"vomar-desktop-1.1.0-linux-x64.zip","size":1,"sha256":"$sha","componentVersion":"1.1.0","platform":"linux","architecture":"x64"},
                {"role":"desktop-windows-x64","filename":"vomar-desktop-1.1.0-windows-x64.zip","size":1,"sha256":"$sha","componentVersion":"1.1.0","platform":"windows","architecture":"x64"},
                {"role":"desktop-windows-setup","filename":"vomar-desktop-1.1.0-setup.exe","size":1,"sha256":"$sha","componentVersion":"1.1.0","platform":"windows","architecture":"x64"},
                {"role":"desktop-macos-arm64","filename":"vomar-desktop-1.1.0-macos-arm64.zip","size":1,"sha256":"$sha","componentVersion":"1.1.0","platform":"macos","architecture":"arm64"},
                {"role":"zigbee2mqtt-converter","filename":"vomar-converter-1.0.0.js","size":1,"sha256":"$sha","componentVersion":"1.0.0"},
                {"role":"licenses","filename":"licenses.txt","size":1,"sha256":"$sha","componentVersion":"2.0.0"},
                {"role":"offline-guide","filename":"offline-guide.zip","size":1,"sha256":"$sha","componentVersion":"2.0.0"},
                {"role":"source-sbom","filename":"source-sbom.json","size":1,"sha256":"$sha","componentVersion":"2.0.0"}
              ]
            }
        """.trimIndent()).jsonObject
    }

    @Test fun syntheticOpenOcdOriginal() {
        val root=File(requireNotNull(System.getProperty("vomar.root")))
        val original=org.openvimar.installer.OriginalArchive.verify(File(root,"tests/contracts/fixtures/openocd-original.zip").readBytes())
        assertEquals(1L,original.identity.uid0);assertEquals(2L,original.identity.uid1)
        original.requireFirstInstallCompatible()
    }

}
