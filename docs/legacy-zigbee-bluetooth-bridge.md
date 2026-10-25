# Prepare a legacy dimmer for Android Bluetooth updates

The local0.6.3 intermediate updates a compatible MAIN0.5.5/REC0.7.1 device
through its existing Zigbee OTA path, then enters REC0.8.3. That recovery keeps
eight stored Bluetooth associations, so the existing PC association can coexist
with a phone. One Bluetooth connection is active at a time; no bond is evicted.

The current prepared files are in
`experiments/firmware/releases/0.6.3/`. The intermediate `.ota` is sent through
Zigbee2MQTT after an exact target/source/OFF check. The common
`qualification-candidate.zip` is selected in the existing Android0.6.3 app,
**Settings → Bluetooth trial**, after the intermediate enters Bluetooth.
They are common artifacts for the finite supported loader set, not per-device
identity packages. Original private stock backups remain separate.

## Operator sequence

1. Save the new complete0.6.3 common ZIP on the phone. Use the existing APK0.6.3.
2. Once preparation is confirmed, switch off the relevant lighting breaker
   for30seconds, then restore power with the dimmer buttons released.
3. Confirm the exact dimmer returns to its original Zigbee network. The update
   operator must verify current source0.5.5 and lamp OFF before sending the
   intermediate; use the intended coordinator and exact target identity.
4. Keep the dimmer powered through Zigbee download and recovery replacement.
   Bluetooth recovery at the end is intentional and remains active until the
   final normal application is installed.
5. Near the dimmer, choose the new ZIP in **Bluetooth trial**, then **Find and
   inspect dimmer**. Complete Android pairing with824005 if requested.
6. Review the selected target and start the trial. After completion verify the
   same Zigbee network, lamp and physical buttons. Save the trial report if
   inspection or transfer fails; inspect durable state before retrying.

## Preparation status

Native builds, public signatures, exact embeddedREC binding, legacy stage bounds,
the frozen old C verifier/SDK decoder, host fault tests and actual Android-core
candidate admission pass. Independent review found no confirmed Critical or
Important source/artifact issue. These checks prepare a controlled local trial;
a later owner-reported phone update through this bridge was corroborated by
post-trial radio diagnostics, without a fresh authenticated full-image hash.
Additional-phone enrollment, output continuity and exact current-release power-cut
qualification remain separate. The thirteen candidate qualification flags stay false.

The final normal application also fixes the confirmed SDK fatal-reset write
that unintentionally selected the loader's recovery mode. The original Zigbee
assertion is still under investigation; the reset-routing correction is not
proof that the originating stack error has been eliminated.

Exact sources, transformations, hashes, review results and limits are recorded
in `experiments/firmware/builds/0.6.3/2026-10-24-legacy-bridge/`.
