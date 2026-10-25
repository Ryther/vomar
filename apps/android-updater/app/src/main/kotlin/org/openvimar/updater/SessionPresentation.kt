package org.openvimar.updater

import org.openvimar.updater.core.Phase
import org.openvimar.updater.core.ValidatedPackage

enum class SessionOperation { IDLE, INSPECT, IMPORT, PROBE, UPDATE, PREPARE, EXPORT, OPERATOR }

/** Identity and display facts only; this summary cannot authorize an update. */
data class PackageSummary(
    val name: String,
    val targetVersion: String,
    val address: String,
    val uid: List<String>,
    val digest: String,
    val mainHash: String,
    val migrationVersion: String
) {
    internal companion object {
        fun from(pkg: ValidatedPackage) = PackageSummary(pkg.manifest.device.name, pkg.manifest.main.version,
            pkg.manifest.device.bleAddress, pkg.manifest.device.uid.toList(), pkg.bundleDigest,
            pkg.manifest.main.signedRegionSha256, pkg.manifest.migration.version)
    }
}

/** UI evidence is read-only. All command authority remains in SessionController/UpdateCoordinator. */
data class SessionPresentation(
    val inspected: Boolean = false,
    val loaded: Boolean = false,
    val busy: Boolean = false,
    val operation: SessionOperation = SessionOperation.IDLE,
    val packageSummary: PackageSummary? = null,
    val hasCheckpoint: Boolean = false,
    val imagesVerified: Boolean = false,
    val resetAcknowledged: Boolean = false,
    val operatorOnline: Boolean? = null,
    /** Latest successful read-only probe for this exact package; never current connection status. */
    val bluetoothVerified: Boolean = false,
    /** Read-only image evidence for the exact selected package. Cleared before each radio operation. */
    val observedMainHash: String? = null,
    val reportAvailable: Boolean = false,
    val phase: Phase? = null,
    val progressPercent: Int? = null
)
