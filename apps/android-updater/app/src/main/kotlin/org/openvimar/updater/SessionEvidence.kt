package org.openvimar.updater

import org.openvimar.updater.core.Checkpoint
import org.openvimar.updater.core.Phase

/** Historical verified transfer evidence is independent of reset response and operator observation. */
data class SessionEvidence(val imagesVerified: Boolean, val resetAcknowledged: Boolean, val needsResetConfirmation: Boolean) {
    companion object {
        fun from(checkpoint: Checkpoint?): SessionEvidence {
            val finalVerified = checkpoint?.phase == Phase.FINAL_RESET_INTENT || checkpoint?.phase == Phase.AWAIT_OPERATOR
            return SessionEvidence(
                imagesVerified = finalVerified,
                resetAcknowledged = finalVerified && checkpoint?.resetAcknowledged == true,
                needsResetConfirmation = checkpoint?.phase == Phase.MIGRATION_RESET_INTENT ||
                    (finalVerified && checkpoint?.resetAcknowledged == false)
            )
        }
    }
}
