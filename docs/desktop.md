# Desktop app and CLI

Native Vomar packages include a GUI and CLI using the same backend. End users
need no Python or firmware SDK. App version and bundle version are independent;
check the installed CLI/app version and exact release manifest.

## Install

| Platform | Package and launch |
| --- | --- |
| Linux x64 | Extract the tar.gz, run `sh Vomar/install.sh` and launch Vomar from the desktop menu. Installed commands are `~/.local/bin/vomar` and `vomar-gui`. |
| Windows x64 | Run the per-user setup executable, or extract the portable ZIP and run `Vomar.exe`. The package also contains `vomar-cli.exe`. |
| macOS Apple Silicon | Open the arm64 DMG and copy Vomar to Applications. The CLI is `Vomar.app/Contents/MacOS/vomar-cli`. |

Target OS floors are Ubuntu 22.04+, Windows 10 1809+/11 and macOS 14.4+ on the
matching architecture. Intel Mac packages are not provided. Each native platform
has separate driver/permission and physical Bluetooth/USB qualification.

Verify release checksums. Windows trusted application signing and macOS trusted
signing/notarization are deferred; macOS uses ad-hoc integrity signing. Use normal
OS approval rather than disabling protection globally. DK access can require
an appropriate libusb/WinUSB driver for the intended probe interface.

Open the app before connecting a device. Devices, Activity and Settings should
be available. `vomar --version` and `vomar --help` inspect the CLI without device work.

## Devices, Activity and Settings

Devices provides optional names/rooms and transport observations. A saved record
or advertised name is not authenticated identity. macOS Bluetooth identifiers
are opaque UUIDs, not MAC addresses to convert manually.

**Settings → Updates** selects a signed common firmware ZIP or GitHub source.
Verification never starts an update. Desktop ZIPs are client installers; choose
the firmware artifact by role and verified content. A compatible local ZIP works
without a GitHub token.

Review a device's Bluetooth update from Devices. Check live identity, loader and
package, then type the displayed challenge to approve that operation. Stop or
restart revokes approval. Activity retains intent, acknowledgment and uncertainty.
An interrupted upload needs the same package/session and fresh live review;
an acknowledged reset is not proof of working lights or radio.

Experimental packages use the separate Bluetooth trial tool, not the ordinary
catalog/fleet route. Read [package rules](offline-guide.md) before selecting one.

## First installation and repair

First installation needs an explicitly authorized isolated bench, with mains
disconnected. Select the exact probe, review HALT and capture two equal complete
originals. Export and reopen the exact original before reviewing FLASH writes.
The installation preserves UICR, commits last, verifies the full image and ends
halted. Verified start requires separate review.

Retain the original, export receipt, release and journal after interruption.
Repair rechecks the exact target and evidence before new review; never-issued
pages must still match the original. Missing/corrupt evidence blocks repair.
A rebuild can discard newer custom settings. There is no implicit mass erase,
recover, UICR programming or startup restoration of hardware consent.

## Optional MQTT and fleet

Configure and explicitly connect one broker, with up to three distinct base
topics. Plaintext local transports require separate consent. Passwords use Secret
Service, Keychain or Windows Credential Manager, without plaintext fallback;
unlock the OS store if needed.

Eligible Zigbee OTA needs exact signed carrier bytes, live compatibility and a
fresh advancing recovery observation. Retained state or a generic OTA flag is
insufficient. A submitted request can continue after local Stop: retain the
uncertain network and perform explicit read-only reconciliation. Scheduling
allows one global Bluetooth operation and one operation per Zigbee network.

## CLI and diagnostics

Use `vomar --help` and the selected subcommand's `--help` for supported commands.
The CLI covers releases, devices, fleet, MQTT, sessions, diagnostics, backup,
probe, first-install, repair, start, trial and Zigbee operations. `preview` is
read-only admission; `run` requests a fresh interactive review. There is no
universal `--yes`. Results go to stdout; progress/errors go to stderr.

`vomar --runtime-info` reports bundled Python/OpenSSL and CA-store metadata
without opening app state or connecting to a broker/device. The explicit
`vomar --runtime-info --tls-self-test` additionally uses disposable certificates
and a bounded `127.0.0.1` listener to test trusted success and untrusted rejection;
it does not change CA preferences or qualify physical transport.

## Upgrade or remove

Wait for owned operations to finish and retain originals/sessions. Install the
matching newer package and verify its native version and retained state. The
Linux `uninstall.sh` removes owned launchers/runtime/icons while retaining private
state and customized replacements. Removing the client does not restore stock
firmware or cancel a submitted remote OTA request.

For source builds, GUI display setup and pinned runtime packaging, use
[Development](development.md#isolated-native-desktop-runtime). For failures, use
[Troubleshooting](troubleshooting.md).
