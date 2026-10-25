package org.openvimar.updater.core

import org.junit.Assert.*
import org.junit.Test
import java.io.File
import kotlinx.serialization.json.Json

class UpdatePlannerTest {
    private val manifest=Json.decodeFromString<Manifest>(File("../test-fixtures/manifest.json").readText())
    private val p=ValidatedPackage(manifest,byteArrayOf(1),byteArrayOf(2),"bundle")
    private fun remote(recovery:String,primary:String?)=RemoteImages(primary?.let { RemoteImage(it,true,true) },RemoteImage(recovery,true,true))
    @Test fun sequenceTable() {
        val m=p.manifest
        listOf(
            Triple(m.legacyRecoverySignedHash,m.allowedSourceSignedHashes.first(),Decision.UploadMigration),
            Triple(m.legacyRecoverySignedHash,m.migration.signedRegionSha256,Decision.RunMigration),
            Triple(m.targetRecoverySignedHash,m.migration.signedRegionSha256,Decision.UploadMain),
            Triple(m.targetRecoverySignedHash,m.allowedSourceSignedHashes.first(),Decision.UploadMain),
            Triple(m.targetRecoverySignedHash,m.main.signedRegionSha256,Decision.ReturnToMain)
        ).forEach { (r,h,d)->assertEquals(d,UpdatePlanner.next(p,remote(r,h),null)) }
    }
    @Test fun unknownHashNeverWrites() {
        assertEquals(Decision.Reject,UpdatePlanner.next(p,remote(manifest.targetRecoverySignedHash,"unknown"),null))
        assertEquals(Decision.Reject,UpdatePlanner.next(p,remote("unknown",manifest.main.signedRegionSha256),null))
    }
    @Test fun missingPrimaryRequiresMatchingSession() {
        val r=remote(manifest.legacyRecoverySignedHash,null)
        assertEquals(Decision.Reject,UpdatePlanner.next(p,r,null))
        val c=Checkpoint(bundleDigest="bundle",bleAddress=manifest.device.bleAddress,phase=Phase.UPLOAD_MIGRATION)
        assertEquals(Decision.UploadMigration,UpdatePlanner.next(p,r,c))
        assertEquals(Decision.Reject,UpdatePlanner.next(p,r,c.copy(bundleDigest="other")))
    }
    @Test fun fullFileHashIsNotImageHash() { assertEquals(Decision.Reject,UpdatePlanner.next(p,remote(manifest.targetRecoverySignedHash,manifest.main.fileSha256),null)) }
    @Test fun resetRequiresExpectedHashAndRecovery() {
        assertEquals(Decision.Reject,UpdatePlanner.next(p,RemoteImages(RemoteImage(manifest.main.signedRegionSha256,true,true),RemoteImage(manifest.targetRecoverySignedHash,false,true)),null))
    }
    @Test fun completeUploadNeverRepeated() {
        val c=Checkpoint(bundleDigest="bundle",bleAddress=manifest.device.bleAddress,phase=Phase.UPLOAD_MAIN)
        assertEquals(Decision.ReturnToMain,UpdatePlanner.next(p,remote(manifest.targetRecoverySignedHash,manifest.main.signedRegionSha256),c))
        assertEquals(Decision.AwaitOperator,UpdatePlanner.next(p,remote(manifest.targetRecoverySignedHash,manifest.main.signedRegionSha256),c.copy(phase=Phase.FINAL_RESET_INTENT)))
    }
}
