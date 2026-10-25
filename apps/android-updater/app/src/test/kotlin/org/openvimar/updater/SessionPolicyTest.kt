package org.openvimar.updater

import org.junit.Assert.*
import org.junit.Test

class SessionPolicyTest {
    @Test fun rotationDoesNotRestartUpload() {
        val policy = SessionPolicy()
        assertTrue(policy.begin(false, false))
        assertFalse(policy.begin(false, false))
    }
    @Test fun cannotReplaceBundleDuringUpdate() {
        val policy = SessionPolicy()
        policy.begin(false, false)
        assertFalse(policy.canReplace)
    }
    @Test fun processReopenRequiresResumeClick() {
        val policy = SessionPolicy(restored = true)
        assertFalse(policy.begin(false, false))
        assertTrue(policy.begin(true, false))
    }
    @Test fun revokedPermissionPauses() {
        assertEquals(listOf("android.permission.BLUETOOTH_SCAN", "android.permission.BLUETOOTH_CONNECT"), PermissionPolicy.required(31))
        assertEquals(listOf("android.permission.ACCESS_FINE_LOCATION"), PermissionPolicy.required(30))
    }
    @Test fun deniedNotificationsDoesNotCreateSecondSession() {
        assertFalse(PermissionPolicy.required(35).contains("android.permission.POST_NOTIFICATIONS"))
    }
    @Test fun uncertainResetRequiresFreshConfirmation() {
        val policy = SessionPolicy(restored = true)
        assertFalse(policy.begin(true, true))
        assertTrue(policy.begin(true, true, confirmed = true))
        policy.finish()
        assertFalse(policy.begin(true, true))
    }
    @Test fun returnToZigbeeNeedsOperatorConfirmation() {
        assertEquals("da confermare", SessionPolicy.operatorOutcome(null))
        assertEquals("tornato online", SessionPolicy.operatorOutcome(true))
        assertEquals("non tornato online", SessionPolicy.operatorOutcome(false))
    }
    @Test fun publicReleaseAccessDoesNotRequireBroadStorageOrAccountPermissions() {
        val manifest = java.io.File("src/main/AndroidManifest.xml").readText()
        assertTrue(manifest.contains("android.permission.INTERNET"))
        listOf("android.permission.READ_EXTERNAL_STORAGE",
            "android.permission.WRITE_EXTERNAL_STORAGE", "android.permission.MANAGE_EXTERNAL_STORAGE",
            "android.permission.GET_ACCOUNTS").forEach { assertFalse(manifest.contains(it)) }
        assertTrue(manifest.contains("android:allowBackup=\"false\""))
        assertTrue(manifest.contains("android:foregroundServiceType=\"connectedDevice\""))
    }

    @Test fun productionAnchorMatchesFirmwarePublicKey() {
        val pem = java.io.File("../../../firmware/keys/dev-public.pem").readText()
        val der = java.util.Base64.getMimeDecoder().decode(pem.lines().filter { !it.startsWith("---") }.joinToString(""))
        assertArrayEquals(der, java.io.File("src/main/res/raw/firmware_public.der").readBytes())
    }
    @Test fun lostFinalResetRetainsVerifiedMainWithoutClaimingAcknowledgement() {
        val checkpoint = org.openvimar.updater.core.Checkpoint(bundleDigest = "a".repeat(64),
            bleAddress = "AA:BB:CC:DD:EE:FF", phase = org.openvimar.updater.core.Phase.FINAL_RESET_INTENT)
        val evidence = SessionEvidence.from(checkpoint)
        assertTrue(evidence.imagesVerified)
        assertFalse(evidence.resetAcknowledged)
        assertTrue(evidence.needsResetConfirmation)
    }

    @Test fun acknowledgedFinalResetNeverRequestsRetry() {
        val checkpoint = org.openvimar.updater.core.Checkpoint(bundleDigest = "a".repeat(64),
            bleAddress = "AA:BB:CC:DD:EE:FF", phase = org.openvimar.updater.core.Phase.AWAIT_OPERATOR,
            resetAcknowledged = true)
        assertFalse(SessionEvidence.from(checkpoint).needsResetConfirmation)
    }
}
