package org.openvimar.updater.core

import kotlinx.serialization.Serializable

@Serializable data class Device(val name:String,val ieee:String,val uid:List<String>,val bleAddress:String)
@Serializable data class ImageMetadata(val file:String,val size:Int,val version:String,val wireVersion:List<Long>,val fileSha256:String,val signedRegionSha256:String)
@Serializable data class Provenance(val deviceDescriptorSha256:String,val otaReleaseSha256:String,val qualificationSha256:String,val migrationInputSha256:String,val migrationReportSha256:String)
@Serializable data class Manifest(val schemaVersion:Int,val bundleId:String,val minAppVersion:String,val device:Device,val legacyRecoverySignedHash:String,val targetRecoverySignedHash:String,val allowedSourceSignedHashes:List<String>,val migration:ImageMetadata,val main:ImageMetadata,val provenance:Provenance?)
data class RawPackage(val manifest:ByteArray,val signature:ByteArray,val migration:ByteArray,val main:ByteArray,val bundleDigest:String)
data class ValidatedPackage(val manifest:Manifest,val migration:ByteArray,val main:ByteArray,val bundleDigest:String,val runtimeIdentity:RuntimeIdentity?=null,val commonManifest:CommonManifest?=null) {
    val targetUid:List<String>? get()=runtimeIdentity?.uid
    val checkpointIdentity:RuntimeIdentity? get()=runtimeIdentity?.takeIf{commonManifest?.schemaVersion==3}
}
internal fun sha256(bytes:ByteArray)=java.security.MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it.toInt() and 255) }
