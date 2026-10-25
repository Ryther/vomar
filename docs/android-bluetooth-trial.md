# Update one mounted dimmer with a Bluetooth trial package

Use **Settings → Tools → Bluetooth trial** in Android app1.0.0 to install a signed
qualification candidate on one dimmer already running this project's firmware.
The dimmer stays mounted and powered. This route does not use the DK.

The current 1.0.0 candidate installs MAIN1.0.0 and recovery1.0.0, migrating an
exactly supported older recovery when necessary. Older 0.6.x candidates retain
their own signed compatibility policies. It is the same ZIP for compatible
dimmers; no per-device package or manually maintained identity file is needed.
The original stock backup remains private and separate.

## Prepare the phone and dimmer

1. Install `vimar-updater-1.0.0.apk` over the existing app. It preserves the
   application ID and signer. Keep the complete shared1.0.0 candidate ZIP on the
   phone; do not extract or edit it.
2. On **older dimmer firmware**, switch the lamp **off before entering Bluetooth**.
   The migration helper validates the existing handoff and can refuse an
   unsupported state rather than rewrite the recovery unsafely.
3. In Home Assistant or Zigbee2MQTT, activate Bluetooth/recovery on the intended
   dimmer. Keep it powered and bring the phone nearby. Activate only the intended
   target while selecting it; several dimmers can advertise the same name.
4. Allow Android Bluetooth permissions. App0.6.3 requests the initial system pairing on the established LE connection before protected notification setup. Accept the system pairing request and
   enter **824005** if Android requests the project's development pairing code.

## Inspect, review and update

1. Open **Settings → Tools → Bluetooth trial → Choose candidate ZIP**. Select the shared
   signed1.0.0 qualification candidate. The app checks its signatures, components
   and exact stored bytes. This selection does not connect or install anything.
2. Tap **Find and inspect dimmer**, then select the intended nearby device.
   Search alone never uploads firmware. An older recovery is identified first
   by its exact approved signed image pair; its UID is verified after the
   self-authorizing migration. Newer recoveries report identity directly.
3. Read the status and tap **Review Bluetooth update**. Check the selected
   Bluetooth address, current/target version and available identity evidence.
   Confirm **Start trial** only for that dimmer. A fresh state check rejects a
   changed target, loader, image pair or checkpoint before mutation.
4. Keep the phone close and the dimmer powered. The foreground notification
   retains the operation across screen changes; **Stop trial** is available
   both in the app and notification. Progress and the current message share
   one status area rather than an accumulating log.
5. After image verification and an acknowledged reset, verify that the dimmer
   returns to its **existing Zigbee network** in HA/Z2M. Check its buttons, lamp
   and dimming. An acknowledged reset alone does not prove those observations.

## Interrupted attempts

Stop prevents subsequent requests and preserves durable progress. It cannot
undo a request already issued. Once stopped, repeat **Find and inspect dimmer**
and review the same candidate and target explicitly before continuing.

If a previous reset was uncertain, the review asks for explicit permission for
one retry of that recorded stage. Merely reopening the screen, granting a
permission, importing a ZIP or restarting the app does not restart an update.
An already observed successful recovery migration does not require another
migration reset. Do not clear app data to force a new attempt.

Use **Save trial report** after a failed inspection as well as an interrupted update. App0.6.2 and later include the attempt's Bluetooth/bond/MTU metadata and Android version for support. Reports identify the selected package,
Bluetooth address and recorded outcome; keep them private. Original stock
backups are separate from trial reports.

## Why the trial has a separate entry

The1.0.0 ZIP is still marked `qualification-candidate`. Normal releases, fleet
updates and Zigbee OTA continue to reject it. This screen authorizes one
explicitly reviewed Bluetooth trial; it neither promotes the candidate to a
qualified release nor changes its thirteen pending qualification flags.

**Settings → Tools → First installation → Qualification options → Bench qualification** remains the separate
phone/DK workflow for an isolated bench target. It is not the mounted-device
Bluetooth update route described here.

The delivered APK's host/emulator checks are software evidence. Earlier phone trials do not qualify every source/recovery pair. Physical
phone pairing, radio and actual lamp acceptance for the exact 1.0.0 set remain
separate from its bounded DK runtime test. See [evidence scope](research-summary.md).
