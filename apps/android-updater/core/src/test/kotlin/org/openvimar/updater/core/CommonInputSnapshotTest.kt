package org.openvimar.updater.core

import java.io.File
import java.security.KeyFactory
import java.security.interfaces.ECPublicKey
import java.security.spec.X509EncodedKeySpec
import org.junit.Assert.*
import org.junit.Test

class CommonInputSnapshotTest {
    @Test fun callerMutationDuringIndependentZipVerificationCannotReplaceTheReturnedAuthority() {
        val directory=File("../../../tools/android/test-fixtures/common-v3-input-alias")
        val a=CommonPackageReader.read(File(directory,"policy-a.zip").inputStream())
        val b=CommonPackageReader.read(File(directory,"policy-b.zip").inputStream())
        val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(File(directory,"public.der").readBytes())) as ECPublicKey
        val raw=b.copy(manifest=a.manifest.copyOf(),signature=a.signature.copyOf())
        var restored=false
        val switchingKey=object:ECPublicKey {
            override fun getAlgorithm()=key.algorithm
            override fun getFormat()=key.format
            override fun getW()=key.w
            override fun getParams()=key.params
            override fun getEncoded():ByteArray {
                if(Thread.currentThread().stackTrace.any{it.className=="org.openvimar.installer.CommonRelease"}) {
                    b.manifest.copyInto(raw.manifest);b.signature.copyInto(raw.signature);restored=true
                }
                return key.encoded
            }
        }
        var observed:ValidatedCommonPackage?=null
        try{observed=CommonPackageValidator.validate(raw,switchingKey,"0.6.0")}catch(_:IllegalArgumentException){}
        assertTrue("Probe must restore the caller-owned arrays during nested verification",restored)
        observed?.let{assertEquals("Returned source policy must belong to the authenticated original ZIP",listOf("cd".repeat(32)),it.manifest.allowedSourceSignedHashes)}
    }
}
