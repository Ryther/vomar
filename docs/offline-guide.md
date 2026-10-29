# Offline installation, packages and recovery

This guide can be read on its own after download. Install a client first;
installing or updating the client never installs firmware on a dimmer. Firmware
work requires a separately authorized operation on the exact target. Published
experimental firmware is not physically qualified by a signature or a host test.

## Check the release and choose a file

Keep the matching `release-manifest.json`, `SHA256SUMS`, release notes and known
issues with your downloaded files. Compare each file's SHA-256 with its entry in
`SHA256SUMS` (for example, `sha256sum FILE` on Linux, `shasum -a 256 FILE` on macOS,
or `Get-FileHash FILE -Algorithm SHA256` in Windows PowerShell). Stop on a mismatch.
Checksums do not replace the app's firmware-signature and compatibility checks.

| File | Purpose |
| --- | --- |
| `vomar-android-VERSION.apk` | Install/update the Android app. |
| Desktop tar.gz, DMG, setup executable or portable ZIP | Install the matching native desktop client. |
| `vomar-firmware-VERSION.zip` | Qualified common firmware, when such a release is available. |
| `vomar-firmware-VERSION-qualification-candidate.zip` | Experimental firmware; requires explicit manual admission and review. |
| `.ota` | Exact Zigbee OTA carrier; not a manually selected common firmware ZIP. |
| Device original ZIP | Private FLASH/FICR/UICR recovery material, specific to one target. |
| Diagnostic report | Recorded observations for troubleshooting; not an original backup. |

`VERSION` in distribution filenames is the bundle version. Native component
versions are in `release-manifest.json`: bundle `1.0.0`, for example, contains
Android `1.1.4`. Never unpack, rename or edit a firmware package to bypass
rejection. An original archive belongs to one device, not to every device that
accepts the shared firmware ZIP.

## Install and verify the client

No device, broker, development SDK or GitHub account is needed for these steps.
Keep devices disconnected until you have checked the client.

**Android (Android 8/API 26 or later):** open the downloaded signed APK on the
phone, review Android's installer-source permission if requested, and confirm
installation. For an existing Vomar installation, install over it. **Do not
uninstall or clear storage.** Android checks package ID `org.openvimar.updater`
and signer continuity; a signer error needs the matching signed APK, not data
deletion. Open Vomar, check its Android version in **Settings**, and confirm that
**Devices**, **Activity** and **Settings** are available. No Bluetooth or USB
permission is needed merely to check the app.

**Desktop:** choose the matching OS and architecture; the runtime is included.

| Platform | Install and start |
| --- | --- |
| Linux x64, Ubuntu 22.04+ target | Extract the tar.gz, run `sh Vomar/install.sh`, then launch Vomar from the desktop menu. CLI: `~/.local/bin/vomar`. |
| Windows x64, Windows 10 1809+/11 target | Run the per-user setup executable, or extract the portable ZIP and run `Vomar.exe`. CLI: `vomar-cli.exe` in the package. |
| macOS Apple Silicon, macOS 14.4+ target | Open the arm64 DMG and copy Vomar to Applications. CLI: `Vomar.app/Contents/MacOS/vomar-cli`. Intel Mac packages are not provided. |

Trusted Windows signing and macOS signing/notarization are deferred; macOS uses
ad-hoc integrity signing. Use normal OS approval, never global protection
disablement. Open **Devices**, **Activity** and **Settings** without a target.
Run the packaged CLI with `--version` and `--help` to verify its native version
and available commands without device work. Native build checks do not qualify
physical Bluetooth/USB on each OS; DK access may need the intended probe driver.

## Update one already-custom dimmer manually

Keep its matching stock original independently before a trial. The Bluetooth
route does not check that you possess this archive. Read the exact release's
known issues and acceptance record, including pending physical checks and
APS-105-5241 when listed. A completed transfer leaves experimental firmware
experimental; catalog, fleet and Zigbee admission remain closed for candidates.

On Android:

1. Keep the complete common firmware ZIP on the phone. Open **Devices → dimmer →
   Update firmware → Choose firmware** and select it. Review any beta/local
   warning. **Updates → Choose local ZIP…** is the qualified-package route.
2. Enter the intended dimmer's supported Bluetooth/recovery mode. For an older
   migration, switch the lamp off before entering Bluetooth. Keep it powered
   and nearby. Grant Bluetooth permissions and accept pairing when requested;
   preserve existing bonds. The project's development recovery uses maintenance
   passkey `824005`; use the exact recovery's instructions.
3. Choose **Inspect device** and the intended target, then **Review Bluetooth
   update**. Inspection never uploads firmware. Check available live identity,
   current/target versions and the selected package. An unsupported legacy
   recovery must pass its exact signed-image compatibility policy; a name alone
   does not identify a device.
4. Confirm **Update firmware** for that target. Keep the phone close and power
   available; **Stop update** remains available in the app/notification.
5. After verification and an acknowledged reset, separately observe Zigbee
   return, buttons, lamp and dimming. The acknowledgment proves none of those.

On components that implement the physical connection selector, hold both keys
for five seconds until the LED alternates violet/green, release both, then press
Down within 30 seconds for Bluetooth service (blue/green). Up instead forgets
the Zigbee network and opens pairing; it is not the Bluetooth choice. Faults or
an incomplete update can keep recovery active. Use only the exact installed
components' supported entry route.

On desktop, use **Devices → Find with Bluetooth**, select the intended row and
check the **Bluetooth target** field. Qualified packages use **Settings → Updates
→ Choose signed ZIP**, then **Devices → Review Bluetooth update**. Experimental
packages use
**Settings → Tools → Choose Bluetooth trial candidate**, then **Review Bluetooth
trial** for the selected target. Review live identity, loader and package, then
type the displayed challenge to approve the operation. A local ZIP needs no
GitHub token. Manual admission may relax outer package signatures; image
signatures, roles, layout, identity and loader checks still apply. It cannot
grant an unsigned watchdog capability.

## First installation and original capture

This is a separate, explicitly authorized isolated-bench procedure. Disconnect
household mains and have the operator check target wiring and supply. Prepare
the intended nRF52840 target, DK/J-Link connection, a compatible complete common
ZIP and independent private backup storage. Android additionally needs a USB
host adapter. The full phone → DK → dimmer route and stock restoration still
need separate physical qualification; this guide supplies neither approval nor
that evidence. MCU detection alone does not identify the commercial model.

For Android, open **Settings → Tools → First installation**:

1. **Choose firmware**, review its type/warning, then **Read connected device**.
   Select the intended J-Link probe if necessary and grant USB permission.
   This reads identity/geometry without halting, resetting or programming it.
2. Choose **Backup**, review **Capture original firmware?**, then confirm
   **Capture backup**. The app checks the watchdog profile; do not bypass a
   refusal. Capture temporarily halts the CPU and reads complete FLASH/FICR/UICR
   twice, comparing every byte, without erasing/programming them.
3. The app saves an immutable private original and reopens it byte for byte,
   without an external file picker. Use **Export backup copy** to retain an
   independent permanent copy. Private save/reopen alone is not an external export.
4. Choose **Install firmware** and review/confirm the exact target. Installation
   records intent before bounded FLASH writes, commits last and verifies the
   complete image and unchanged UICR. A supported permission-preparation reset
   retains HALT; it does not write ACL/UICR registers.
5. Successful installation ends **halted**. Choose **Start verified firmware**
   and separately confirm **Start firmware**. The app rechecks identity,
   FLASH/FICR/UICR and watchdog before starting from the verified reset vector.
   A signed inherited-watchdog handoff may wait for one genuine watchdog reset.
6. Observe buttons, lamp, Bluetooth and Zigbee separately after start.

Desktop requires an external export/reopen: choose the firmware under
**Settings → Updates** (or **Tools → Choose Bluetooth trial candidate** for an
explicit candidate bench trial), enter the **DK serial number**, and use
**Review DK halt** (candidate: **Review candidate bench halt**). After fresh
review, use **Capture and export original**, then **Reopen protected original**
on that exact archive. Review **Review first installation** (candidate:
**Review candidate bench installation**). Successful verified writes end halted;
**Review verified start** (candidate: **Review candidate bench start**) is a
separate review. Confirm each displayed challenge only for the intended action.

Keep phone, DK and target connected during active work. Opening a screen,
granting a permission or selecting another device never approves a write/start.
Android **DK tools** is a separate read-only monitor/backup tool.

## Interruption, repair and retention

Stop prevents subsequent requests; it cannot undo a write already issued. A lost
connection or acknowledgment can leave the result uncertain. Keep the exact
package, original, journal, diagnostic report and last reported CPU disposition.
After possible first-install mutation, cleanup retains HALT and requests no
start. Do not release an uncertain halted CPU or recapture partially modified
FLASH as a replacement original. Restart restores records, never approval,
connections or a running operation.

For an interrupted Android first installation:

1. Reopen the retained attempt with the same firmware and **Read connected
   device**. Reuse its private verified original; an older external receipt can
   use **Choose existing original backup** with the exact export.
2. Choose **Prepare repair preview**. It pauses/checks the target and retained
   evidence without programming FLASH. Changed identity, package, original or
   journal head blocks repair.
3. Choose **Review and repair**, then freshly confirm **Continue repair**.
   Repair may verify only, finish a missing commit or rebuild bounded pages;
   never-issued pages must match the original. Rebuilding discards newer custom
   settings while retaining the original.
4. Successful repair again ends halted. **Start verified firmware** requires
   its separate review; another interruption requires a new preview/review.

On desktop, select the retained attempt in **Activity**, reopen the exact
original/package, and use **Settings → Tools → Review interrupted installation
repair** (candidate: **Review candidate bench repair**). Start remains separate.
Missing/corrupt evidence and unknown bytes block repair. An acknowledged start
suppresses Android first-install repair; it is not a factory-reset shortcut.

For Bluetooth interruption, inspect/review the same target and package before
continuing. An uncertain reset may need explicit permission for one recorded
retry. Use Android **Export update report** after failed inspection/transfer;
reports are not original backups. A Zigbee OTA request already submitted can
continue after local Stop; explicitly reconcile network state read-only before
another operation. Never use mass erase, `recover`, UICR writes or journal
deletion as generic repair.

Keep each original ZIP intact and private: it contains `flash.bin`, `ficr.bin`,
`uicr.bin`, metadata and potentially network/device identity. Android
**Devices → device → Original firmware** exports a retained copy; restoration
is a separately reviewed DK operation against matching live identity/FICR/UICR,
with bounded FLASH verification ending halted. Capturing an original does not
prove physical restoration qualification.

Wait for active operations to end before upgrading a client. **Android
uninstall/Clear storage deletes private originals, sessions, settings and
credentials; automatic Android backup is disabled.** Export originals first and
retain them permanently. Exports already stored elsewhere survive independently;
an original ZIP/report is not a complete app-state backup. Desktop Linux
`uninstall.sh` retains private state while removing owned launchers/runtime.
Removing any client does not restore device firmware or cancel a remote OTA.

Optional online help, when a network is available:
[release notes and matching assets](https://github.com/Ryther/vomar/releases) and
[current manuals](https://ryther.github.io/vomar/). Check the release manifest's
source revision before applying newer online instructions to an older package.
For support, share app/OS and package versions, phase and sanitized errors;
keep originals, keys, credentials, full identities and raw captures private.
