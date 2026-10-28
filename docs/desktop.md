# Desktop application

The GUI uses the Vomar amber V/open-switch icon in its header and system identity.
Native packages include the corresponding Windows executable/installer icon,
macOS application icon and Linux launcher icons. The per-user Linux uninstaller
removes its matching icon copies and preserves customized replacements.

Native packages provide `Vomar` (GUI) and `vomar-cli` (CLI), sharing the same Python
engine. End users need no Python, Nordic SDK, Gradle or development container.
Each supported platform is built separately; a Linux test does not qualify
Windows/macOS drivers or Bluetooth.

The desktop component is version 1.1.1. The CLI, Windows installed application
and executable metadata, and macOS bundle metadata use that native version.
Download filenames use the coordinated distribution version, which can differ.

## Install

- Linux x64: extract the tar.gz, run `sh Vomar/install.sh`, and open Vomar from
  the desktop menu. `~/.local/bin` provides the `vomar` and `vomar-gui` launchers. Use the shipped
  uninstall script to remove only the owned runtime; private data is retained.
- Windows x64: use the per-user installer or extract the portable ZIP. Approve
  the unsigned application through the normal Windows first-launch flow after
  checking the downloaded distribution checksums. DK USB access may require a
  compatible libusb/WinUSB driver selected deliberately for the probe interface.
- macOS Apple Silicon (arm64): choose the arm64 DMG and copy Vomar to
  Applications. The CLI is `Vomar.app/Contents/MacOS/vomar-cli`. The initial bundle
  has ad-hoc integrity signing, without a trusted developer certificate or
  notarization. Use System Settings' normal approval flow. Bluetooth access is
  requested only when you initiate a scan/connection.

Intel Mac packages are not currently provided.

The target contracts are Ubuntu 22.04+ x64, Windows 10 1809+/11 x64 and macOS
14.4+ on the matching architecture. Native runner checks and linked-library
inspection must establish the actual package floor; host-only tests do not.

## Devices, Activity and Settings

Devices is optional organization: discover a nearby recovery, then save a name
and room if useful. Manual updates do not require a registry. A macOS Bluetooth
identifier is an opaque UUID; do not convert it into a MAC address.

Settings → Updates accepts one signed local common ZIP or the public GitHub
source. Multiple desktop ZIPs in a release are harmless: clients use explicit
firmware role, canonical name and exact download bytes. A local older supported
ZIP still works without a GitHub token. Verification never starts an update.

Review Bluetooth updates from Devices. Review names the live UID, approved loader,
package and observed images; type the displayed challenge to approve that one
operation. Stop and process restart revoke approval. Activity preserves intent,
progress, acknowledgment and uncertainty. Acknowledged reset is not verified
physical operation. Confirm actual device operation separately after observing it.

An interrupted upload requires the same session, package and fresh live review.
A completed acknowledged reset is not silently repeated. The separate Bluetooth
trial tool accepts signed qualification candidates for a single controlled target;
those candidates cannot enter the normal release/fleet/Zigbee route.

## First installation and repair

Use an isolated bench with mains disconnected. MCU identity alone does not prove
the commercial hardware model. Select the exact DK serial, review HALT and keep
the exclusive connection while acquiring two equal FLASH/FICR/UICR reads. Export
and reopen the exact protected original before reviewing FLASH programming.
No UICR write, mass erase or automatic recovery operation exists in this route.

Installation writes bounded FLASH pages, verifies them, commits the anchor last,
then verifies the complete image and unchanged UICR. It ends halted. Verified
start is a separate review. Never disconnect or release an uncertain target on
an assumption that a transfer succeeded.

For repair, retain the initial original/export and select the interrupted session.
Fresh preview checks the same release/target/original and journal head. Pages
never issued by the journal must still match the original. Rebuild may discard
custom settings. Changed originals, missing journals or unknown memory block
repair. No startup path restores hardware consent.

## Optional MQTT and fleet

One explicitly connected broker supports up to three distinct Zigbee2MQTT base
topics. Private brokers are supported independently of public release HTTPS
policy. Unencrypted TCP/WebSocket connections require separate local-network
consent. Passwords use Secret Service, Keychain or Windows Credential Manager;
there is no plaintext fallback. Unlock the OS store if it is unavailable.

A Zigbee update requires the exact HTTPS carrier bytes bound by the signed
package, a supported custom target, correlated OTA check and a fresh advancing
recovery contract. Retained state is a baseline, not proof. A submitted uncertain
update holds its network until explicit read-only reconciliation; cancellation
does not cancel a remote Zigbee2MQTT operation. One global BLE operation and one
operation per network limit concurrency. Saved labels never replace identity.

## CLI and developer rebuild

For an interactive source checkout, install the locked desktop dependencies in
a separate Python 3.13 environment, then run from the repository root:

```sh
PYTHONPATH="$PWD/apps/desktop-updater/src" python -m vomar_updater.gui.app --state "$PWD/_test/desktop-manual-state"
```

The development image includes Qt's X11 runtime dependencies. The default
Dev Container does not forward a host display. An interactive container needs
the host X11 socket, the matching `DISPLAY`, and host display authorization;
setting `DISPLAY` alone is insufficient. With the host socket deliberately
mounted and the container UID matching the desktop user's UID, run
`xhost +SI:localuser:"$(id -un)"` in a **host** terminal before launching the GUI.
Remove that grant afterward with `xhost -SI:localuser:"$(id -un)"` on the host.
A missing Qt library and a display authorization failure are separate errors.
For a startup check without a host display, use `xvfb-run -a` with
`QT_QPA_PLATFORM=xcb` and the GUI's `--smoke-test` option; this does not verify
interaction on the host desktop or Bluetooth/USB operations.

`vomar --help` lists releases, devices, fleet, MQTT, sessions, diagnostics, backup,
probe, first-install, repair, start, trial and Zigbee commands. `preview` is
read-only admission; `run` prepares and prints a fresh interactive review.
There is no universal `--yes` or replayable approval file. Machine-readable
results go to stdout; progress and errors go to stderr.

`vomar --runtime-info` reports the bundled Python/OpenSSL versions and platform
default CA-store metadata without opening application state or connecting to a
service. It does not disclose user-supplied CA paths. The explicit
`vomar --runtime-info --tls-self-test` additionally creates temporary test-only
certificates and a bounded listener on literal `127.0.0.1`, verifies a trusted
connection and rejection of an untrusted certificate, then removes its temporary
files. It never connects to a broker or device and does not alter CA preferences.

Native builds use the checksum-pinned whole Astral Python Build Standalone
20261026 runtime: CPython 3.13.18 with OpenSSL 3.5.9, in an isolated desktop venv.
Follow the [desktop runtime rebuild](development.md#isolated-native-desktop-runtime)
procedure; the development container and firmware SDK keep Python 3.13.12.
Packaging checks the actual frozen CLI identity and loopback TLS behavior and
binds the observed results, provider archive/source hashes and runtime binary
hashes into each shipped native inventory. Native runner tests still need to
establish each platform's default certificate-store usability.

Build on the target OS/architecture. The onedir runtime links Qt dynamically;
upstream license texts and build inventory ship under notices. Replacing Qt
libraries or rebuilding is supported subject to their upstream ABI/license.
Trusted OS signing remains deferred; firmware and Android signer continuity are
mandatory and separate. See [release preparation](releasing.md).
