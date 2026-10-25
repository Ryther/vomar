package org.openvimar.updater

import org.openvimar.updater.core.*

/** Presentation only: never grants authority to upload, reconnect or reset. */
internal object UpdateCopy {
    /** Reports retain full diagnostic detail; the status area keeps the next action visible. */
    fun visibleStatus(message: String): String = message.substringBefore("\nTechnical detail:")
        .substringBefore("\nDettaglio tecnico:").substringBefore("\nDettagli tecnici:")

    fun describe(event: UpdateEvent): String = when (event) {
        is UpdateEvent.Progress -> {
            val subject = if (event.phase == Phase.UPLOAD_MIGRATION) "Bluetooth recovery" else "firmware"
            "Transferring $subject: ${event.acknowledgedOffset * 100L / event.total}%"
        }
        is UpdateEvent.Planned -> when (event.decision) {
            Decision.UploadMigration -> "Preparing the Bluetooth recovery update…"
            Decision.RunMigration -> "Starting the Bluetooth recovery update. Wait for reconnection."
            Decision.UploadMain -> "Preparing the new firmware…"
            Decision.ReturnToMain -> "Firmware verified. Sending the restart request…"
            Decision.AwaitOperator -> "Firmware verified. Check that the dimmer is online in Home Assistant or Zigbee2MQTT."
            Decision.Reject -> "Installed images do not match this package. Update blocked. Export the report for diagnosis."
        }
        is UpdateEvent.Reconnecting -> "Bluetooth reconnect: retry in ${event.delayMillis / 1_000} s (${event.attempt} of 3)."
        is UpdateEvent.Paused -> "Paused: ${failure(event.reason)}"
        is UpdateEvent.AwaitingOperator -> if (event.resetAcknowledged) {
            "Firmware verified; the dimmer acknowledged the restart request. Check in Home Assistant or Zigbee2MQTT that it is online, then record the result here."
        } else {
            "Firmware verified; restart was not acknowledged. Check in Home Assistant or Zigbee2MQTT that the dimmer is online, then record the result here."
        }
        UpdateEvent.Stopped -> "Operation stopped. Progress saved; choose Resume to check the dimmer state."
    }
    fun failure(message: String?): String = when (message) {
        "Unexpected recovery or primary image", "Images changed before reset", "Unexpected images after final reset" ->
            "Installed firmware does not match the package’s expected state. Operation blocked. Export the report for diagnosis."
        "Upload verification failed", "Device reports full-file hash mismatch" ->
            "Transferred firmware failed verification. No restart requested at this stage. Export the report for diagnosis."
        "Migration reconnect window expired" ->
            "Bluetooth recovery did not reconnect in time. Move the phone closer and choose Resume. If this continues, export the report."
        "Reconnect limit reached" ->
            "Bluetooth connection lost after three reconnect attempts. Move the phone closer and choose Resume to check the dimmer."
        "Session identity/schema mismatch" ->
            "The saved session does not match this package. Import the correct package for your dimmer. If this continues, export the report."
        "Android authenticated bond required; pair using system UI" ->
            "Android pairing is incomplete. Complete the system request and retry the operation."
        null, "" -> "Operation not completed. Export the report for diagnosis."
        else -> if (listOf("Bluetooth", "Android", "Import ", "Package ", "Session ", "Confirmation ", "Wait", "Connection", "Device", "Operation", "Destination", "The ", "No ", "Cannot ", "Runtime ", "Legacy ", "Recovery ", "Previously ", "Shared ").any { message.startsWith(it) }) message
            else "Operation not completed. Export the report for diagnosis.\nTechnical detail: $message"
    }
}
