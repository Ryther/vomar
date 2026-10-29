# Packages, originals and recovery

A Vomar release contains shared installers and firmware. A device's original
backup belongs to that device and stays private. These files are not interchangeable.

## Choose the right file

| File | Purpose |
| --- | --- |
| `vomar-android-VERSION.apk` | Install/update the Android app. |
| Desktop tar.gz, DMG, setup executable or portable ZIP | Install the matching native desktop client. |
| `vomar-firmware-VERSION.zip` | Qualified common firmware, when such a release is available. |
| `vomar-firmware-VERSION-qualification-candidate.zip` | Experimental firmware; requires explicit manual admission and review. |
| `.ota` | Exact Zigbee OTA carrier; not a manually selected common firmware ZIP. |
| Device original ZIP | Private FLASH/FICR/UICR recovery material, specific to one target. |
| Diagnostic report | Recorded observations for troubleshooting; not an original backup. |

`VERSION` in distribution filenames is the bundle version. Native versions are
in `release-manifest.json`; checksums are in `SHA256SUMS`. The app separately
checks firmware signatures, component roles, layout and loader compatibility.
Never unpack, rename or edit a package to bypass rejection.

## Experimental firmware

Read the exact release's known issues and acceptance record. Android chooses
experimental firmware through **Devices → dimmer → Update firmware → Choose
firmware**; desktop has a separate Bluetooth trial route. Ordinary catalog,
fleet and Zigbee admission remains closed for candidates. A published OTA asset
is not automatic-update approval.

The published experimental acceptance records pending physical checks and the
unresolved APS-105-5241 restart issue. A host test, signature or green badge does
not complete those checks. See [release preparation](releasing.md) for the
publisher contract and [research evidence](research-summary.md) for bounded observations.

## Keep recovery material

Keep one immutable original archive per device in independent private storage.
Android captures and reopens a private copy; external export is an additional
user action. Desktop requires its explicit export/reopen. Before uninstalling
Android, export each original you need: uninstall/Clear storage deletes private
originals, sessions, settings and credentials. Files already exported elsewhere
survive independently; an original export is not a complete app-state backup.

After interruption, preserve the package, original and journal. Use explicit
resume/repair for the same target and bytes, with a fresh review. Missing or
changed evidence blocks repair. Successful first-install readback ends halted;
start is separately reviewed. Never use mass erase, recover, UICR writes or an
automatic CPU release as generic repair.

Follow [First installation](android-first-install.md),
[Bluetooth updates](android-bluetooth-trial.md) or
[Troubleshooting](troubleshooting.md) for the operation you were performing.
