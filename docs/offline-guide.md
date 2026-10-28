# Installation and recovery guide

This guide accompanies the coordinated Vomar distribution. It contains no device
backup, household configuration, account credential or signing key.

1. Choose the Android APK or native desktop package for your actual platform.
   Desktop packages target Linux x64, Windows x64 and macOS Apple Silicon (arm64).
   Check SHA256SUMS against release-manifest.json. Desktop trusted OS signing is
   deferred; firmware/APK cryptographic signing remains mandatory.
2. For qualified firmware choose `vomar-firmware-VERSION.zip`. An explicitly
   accepted experimental distribution instead contains
   `vomar-firmware-VERSION-qualification-candidate.zip` and
   `vomar-release-acceptance-VERSION.json`. Read the acceptance record and known
   issues before selecting those bytes through manual candidate import. Android
   uses its firmware chooser; desktop uses the separate Bluetooth trial tool.
   Automatic firmware catalog/fleet/Zigbee selection rejects the experimental
   package. The app independently verifies signatures, roles, layout and loader.
   Desktop ZIPs are installers. Do not unpack firmware to bypass admission.
3. For an already compatible dimmer, enter the project's Bluetooth recovery,
   select the nearby target, read its live identity and review the operation.
   Do not approve from a radio name or saved room alone. A stable HTTPS carrier
   can alternatively support a qualified eligible Zigbee2MQTT update after fresh
   checks. The experimental OTA asset is not an automatic update approval.
4. First installation is an isolated bench procedure, with mains disconnected.
   Select the exact DK, explicitly review HALT, acquire two equal full originals,
   save privately and reopen the same bytes. Android 1.0.6 keeps this verified
   original on the phone and offers an additional export; desktop requires its
   explicit export/reopen. Keep an independent original copy before deleting app
   data. Only then review installation.
   Preserve the original permanently; it is specific to that physical target.
5. Successful FLASH readback ends halted. Review verified start separately.
   Acknowledged transfer/reset is not proof that lamp, buttons, Zigbee or BLE work.
   Observe those functions physically and retain qualification separately.
6. After interruption, stop and retain the target state, original and journal.
   Review explicit repair/resume for the same target/release/original. Never
   recover, mass erase, change UICR or release an uncertain CPU automatically.
7. Ordinary uninstall preserves private sessions, originals and credentials.
   Diagnostic export is intentional and may contain device identity: share it
   privately after review, never as a public GitHub release asset.

Experimental firmware retains all thirteen pending physical-check flags. The
release acceptance binds the owner's distribution decision to exact payload
hashes and discloses unverified native checks; it does not certify those tests.
The known APS-105-5241 assert can restart Zigbee firmware and remains unresolved.
A passing host test or downloaded package is not physical qualification.
