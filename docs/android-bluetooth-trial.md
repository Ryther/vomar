# Update one device over Bluetooth

Use **Devices → device → Update firmware** in Android app1.0.6 to select a
compatible Vomar package for one dimmer already running this project's firmware.
The dimmer stays mounted and powered. This route does not use the DK.

The current 1.0.0 candidate installs MAIN1.0.0 and recovery1.0.0, migrating an
exactly supported older recovery when necessary. Older 0.6.x candidates retain
their own signed compatibility policies. It is the same ZIP for compatible
dimmers; no per-device package or manually maintained identity file is needed.
The original stock backup remains private and separate.

## Prepare the phone and dimmer

1. Install `vimar-updater-1.0.6.apk` over the existing app. It preserves the
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

1. Open **Devices → device → Update firmware → Choose firmware**. Select the shared
   signed1.0.0 qualification candidate. The app checks its signatures, components
   and exact stored bytes. This selection does not connect or install anything.
2. Tap **Inspect device**, then select the intended nearby device.
   Search alone never uploads firmware. An older recovery is identified first
   by its exact approved signed image pair; its UID is verified after the
   self-authorizing migration. Newer recoveries report identity directly.
3. Read the status and tap **Review Bluetooth update**. Check the selected
   Bluetooth address, current/target version and available identity evidence.
   Confirm **Update firmware** only for that dimmer. A fresh state check rejects a
   changed target, loader, image pair or checkpoint before mutation.
4. Keep the phone close and the dimmer powered. The foreground notification
   retains the operation across screen changes; **Stop update** is available
   both in the app and notification. Progress and the current message share
   one status area rather than an accumulating log.
5. After image verification and an acknowledged reset, verify that the dimmer
   returns to its **existing Zigbee network** in HA/Z2M. Check its buttons, lamp
   and dimming. An acknowledged reset alone does not prove those observations.

## Interrupted attempts

Stop prevents subsequent requests and preserves durable progress. It cannot
undo a request already issued. Once stopped, repeat **Inspect device**
and review the same candidate and target explicitly before continuing.

If a previous reset was uncertain, the review asks for explicit permission for
one retry of that recorded stage. Merely reopening the screen, granting a
permission, importing a ZIP or restarting the app does not restart an update.
An already observed successful recovery migration does not require another
migration reset. Do not clear app data to force a new attempt.

Use **Export update report** after a failed inspection as well as an interrupted update. App0.6.2 and later include the attempt's Bluetooth/bond/MTU metadata and Android version for support. Reports identify the selected package,
Bluetooth address and recorded outcome; keep them private. Original stock
backups are separate from trial reports.

## Local packages and selected devices

The manual device route accepts compatible qualified, beta and local common
packages. Outer artifact signatures may be absent in a local package; image
signatures and structural/compatibility checks remain required. The final review
warns about local/beta firmware. This does not qualify it for fleet or Zigbee OTA.
A saved Bluetooth address selects the inspection target. When a UID is known,
live identity must match it; older recovery verifies the UID immediately after
recovery preparation, before recording that identity or uploading MAIN.

**Settings → Tools → First installation** remains the phone/DK workflow for a
stock target. It uses the same single **Choose firmware** action.

The delivered APK's host/emulator checks are software evidence. Earlier phone trials do not qualify every source/recovery pair. Physical
phone pairing, radio and actual lamp acceptance for the exact 1.0.0 set remain
separate from its bounded DK runtime test. See [evidence scope](research-summary.md).

## Explicit Zigbee pairing on supporting firmware

The feature-branch Android client adds **Devices → device → Zigbee pairing**.
Inspect without selecting a firmware package, then review and explicitly confirm
replacement of the current Zigbee network. Supporting MAIN/recovery performs a
two-minute pairing window; unsupported recovery is refused without a reset
fallback. See [Connection modes](connection-modes.md) for physical entry, colours,
retained settings and uncertain-acknowledgment handling. Existing released packages
and physical qualification are not upgraded by this source change.
