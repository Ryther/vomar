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
    @Test fun syntheticOpenOcdOriginal() {
        val root=File(requireNotNull(System.getProperty("vomar.root")))
        val original=org.openvimar.installer.OriginalArchive.verify(File(root,"tests/contracts/fixtures/openocd-original.zip").readBytes())
        assertEquals(1L,original.identity.uid0);assertEquals(2L,original.identity.uid1)
        original.requireFirstInstallCompatible()
    }

}
