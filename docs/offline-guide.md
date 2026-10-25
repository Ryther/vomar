# Installation and recovery guide

This guide accompanies the coordinated Vomar distribution. It contains no device
backup, household configuration, account credential or signing key.

1. Choose the Android APK or native desktop package for your actual platform.
   Check SHA256SUMS against release-manifest.json. Desktop trusted OS signing is
   deferred; firmware/APK cryptographic signing remains mandatory.
2. Choose the one `vomar-firmware-VERSION.zip`. The app independently verifies
   its signature, roles, layout and approved loader. Desktop ZIPs are installers.
   Do not unzip or substitute image files to bypass package admission.
3. For an already compatible dimmer, enter the project's Bluetooth recovery,
   select the nearby target, read its live identity and review the operation.
   Do not approve from a radio name or saved room alone. A stable HTTPS carrier
   can alternatively support an eligible Zigbee2MQTT update after fresh checks.
4. First installation is an isolated bench procedure, with mains disconnected.
   Select the exact DK, explicitly review HALT, acquire two equal full originals,
   save privately, export and reopen the same bytes. Only then review installation.
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

Current firmware 1.0.0 has thirteen physical qualification checks pending. A
candidate, successful host test or downloaded package is not a qualified hardware
release. Use only an operator-controlled qualification process until matching
physical evidence exists.
