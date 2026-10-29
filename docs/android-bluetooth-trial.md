# Update one device over Bluetooth

Use this route for one dimmer already running compatible Vomar firmware. It
requires no DK. First installation on stock hardware is a separate
[isolated bench procedure](android-first-install.md).

The shared common firmware ZIP serves compatible devices; the app determines
compatibility from the signed package and live target. Do not prepare per-device
firmware or a manually maintained identity file. Keep the original backup privately.

## Prepare the phone and dimmer

1. Update the [Android app](android-updater.md#install-and-track-with-obtainium)
   over the installed copy, retaining its data. Keep the complete firmware ZIP
   on the phone and read its release notes and experimental limits.
2. For an older recovery migration, switch the lamp **off before entering
   Bluetooth**. Unsupported handoff states can be refused rather than rewritten.
3. Enter Bluetooth/recovery on the intended dimmer using its supported control
   or [connection selector](connection-modes.md). Keep it powered and nearby;
   several dimmers may advertise the same name.
4. Grant Bluetooth permissions. Accept the Android pairing request when shown.
   The project's development recovery uses public maintenance passkey `824005`;
   confirm the exact release/recovery instructions. Preserve existing bonds and
   do not delete them to work around an unexplained connection failure.

## Inspect, review and update

1. Open **Devices → device → Update firmware → Choose firmware**. Select the
   complete shared package. A beta/local package shows its separate warning;
   image signatures and compatibility remain checked. Selection starts no update.
2. Choose **Inspect device** and the intended nearby target. Inspection alone
   never uploads firmware. A supported legacy recovery is verified by its exact
   signed image pair before preparation; newer recoveries report identity directly.
3. Choose **Review Bluetooth update**. Check the selected target, available live
   identity evidence and current/target versions. Confirm **Update firmware**
   only for that dimmer. Changed target/package/checkpoint evidence blocks work.
4. Keep the phone close and the dimmer powered. The foreground notification
   retains progress across screen changes. **Stop update** is available in the
   app and notification.
5. After verification and an acknowledged reset, separately observe return to
   the existing Zigbee network and check buttons, lamp and dimming. The
   acknowledgment itself does not establish those results.

Experimental firmware stays experimental after a successful transfer. It does
not gain automatic fleet/Zigbee admission from this manual trial.

## Interrupted attempts

Stop prevents subsequent requests and preserves durable progress; it cannot undo
a request already issued. Keep the package, original and report. Inspect and
review the same target and package explicitly before continuing.

An uncertain reset can require fresh permission for one retry of the recorded
stage. Reopening the app, importing a ZIP or granting a permission never retries
it automatically. A migration already observed as successful is not repeated
merely because the screen reopened. Do not clear app data to force a new attempt.

Use **Export update report** after failed inspection or interrupted transfer.
Reports include bounded connection/OS metadata and recorded outcomes; keep them
private and review them before sharing. They are separate from original backups.
For a legacy target that cannot pass inspection, consult the
[legacy compatibility reference](legacy-zigbee-bluetooth-bridge.md).
