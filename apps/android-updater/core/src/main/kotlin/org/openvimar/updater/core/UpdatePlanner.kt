package org.openvimar.updater.core

enum class Decision { UploadMigration, RunMigration, UploadMain, ReturnToMain, AwaitOperator, Reject }
object UpdatePlanner {
    fun matches(pkg:ValidatedPackage,c:Checkpoint?)=c!=null && c.schemaVersion==1 && c.targetUid==pkg.targetUid && c.runtimeIdentity==pkg.checkpointIdentity && c.bundleDigest==pkg.bundleDigest && c.bleAddress==pkg.manifest.device.bleAddress
    fun next(pkg:ValidatedPackage,remote:RemoteImages,checkpoint:Checkpoint?):Decision {
        val m=pkg.manifest; val r=remote.recovery
        val legacy=pkg.commonManifest?.legacyRecoverySignedHashes ?: listOf(m.legacyRecoverySignedHash)
        if(!r.active || !r.bootable || r.hash !in legacy+listOf(m.targetRecoverySignedHash)) return Decision.Reject
        val c=checkpoint?.takeIf { matches(pkg,it) }
        val h=remote.primary?.hash
        if(h==null) return when {
            r.hash in legacy && c?.phase==Phase.UPLOAD_MIGRATION -> Decision.UploadMigration
            r.hash==m.targetRecoverySignedHash && c?.phase==Phase.UPLOAD_MAIN -> Decision.UploadMain
            else -> Decision.Reject
        }
        if(remote.primary.bootable.not()) return Decision.Reject
        if(r.hash in legacy) return when(h) {
            m.migration.signedRegionSha256 -> Decision.RunMigration
            in m.allowedSourceSignedHashes -> Decision.UploadMigration
            else -> Decision.Reject
        }
        return when(h) {
            m.main.signedRegionSha256 -> if(c?.phase in listOf(Phase.FINAL_RESET_INTENT,Phase.AWAIT_OPERATOR)) Decision.AwaitOperator else Decision.ReturnToMain
            m.migration.signedRegionSha256 -> Decision.UploadMain
            in m.allowedSourceSignedHashes -> Decision.UploadMain
            else -> Decision.Reject
        }
    }
}
