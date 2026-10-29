# Install Vomar

Install the app first. You do not need a connected dimmer, broker, DK, GitHub
account or development SDK. App installation does not start a device operation.

## Android

Requires Android 8.0 (API 26) or later.

Use **[Install with Obtainium](android-updater.md#install-and-track-with-obtainium)**
to receive Android app updates. If Vomar is already installed from an APK, update
over it with the same signing identity. **Do not uninstall or clear app data.**

Alternatively, download the signed `vomar-android-VERSION.apk` from the
[project releases](https://github.com/Ryther/vomar/releases/latest), check its
entry in `SHA256SUMS`, open it and confirm Android's installer. Review permission
for the installer source when Android requests it. `VERSION` in an asset filename
is the **bundle** version; the APK has its own Android version.

Open Vomar and check its app version in **Settings**. Devices and Settings are
available before connecting a broker or dimmer. Grant Bluetooth or USB permission
only when using the corresponding action.

## Desktop

Download the package for your platform from the same release. Check its checksum
before opening it. The package includes its runtime: no Python or SDK installation
is required.

| Platform | Install |
| --- | --- |
| Linux x64, Ubuntu 22.04+ target | Extract the tar.gz into a new directory, run `sh Vomar/install.sh` there, then launch Vomar from the desktop menu. |
| Windows x64, Windows 10 1809+/11 target | Run the per-user setup executable, or extract the portable ZIP. |
| macOS Apple Silicon, macOS 14.4+ target | Open the arm64 DMG and copy Vomar to Applications. Intel Mac packages are not provided. |

Desktop trusted OS signing/notarization is deferred; macOS packages use ad-hoc
integrity signing. Use the OS's normal approval flow after verifying the download,
without disabling system protection globally. Native driver and Bluetooth/USB
compatibility still need verification on the actual platform.

Open Devices, Activity and Settings. On Linux, `vomar --version` and
`vomar --help` also verify the installed command without a device operation.
See [Desktop](desktop.md) for packaged CLI locations and optional connections.

## Before selecting device firmware

Read the release notes, component versions and qualification record. The
`release-manifest.json` identifies each artifact and native component version;
`SHA256SUMS` checks download integrity. The app separately verifies firmware
signatures and device compatibility.

Use a complete firmware ZIP, not a desktop archive, OTA carrier or extracted
binary. The published experimental package uses
`vomar-firmware-VERSION-qualification-candidate.zip`. Android selects it through
**Devices → dimmer → Update firmware → Choose firmware**. The ordinary
**Updates → Choose local ZIP…** route accepts qualified packages. Desktop has a
separate Bluetooth trial route. See [packages and backups](offline-guide.md).

Package selection alone grants no write permission. First installation is a
separate [isolated bench procedure](android-first-install.md); an update of an
already-custom dimmer uses [Bluetooth review](android-bluetooth-trial.md).

## Optional Zigbee2MQTT connection

Configure a broker only if you use Zigbee2MQTT. Android's entry is
**Settings → Zigbee2MQTT**; desktop provides MQTT settings. Save the exact host,
port, transport and base topics, then connect explicitly. Plaintext local
connections require separate consent. Credentials remain private.

A connected broker provides observations, not firmware permission. Saved readings
may be stale. Follow [Android connections](android-updater.md#automatic-zigbee2mqtt-connection)
or [Desktop MQTT](desktop.md#optional-mqtt-and-fleet) for verification.

## Upgrade or remove a client

Wait for any active operation to end. Keep originals and interrupted-session
records, install the matching app upgrade, then check the version and retained
state. Updating the app never updates dimmer firmware automatically.

**Android uninstall or Clear storage deletes private originals, sessions,
settings and credentials.** Export each required original to independent private
storage first. Files exported to Documents or a PC survive independently, but
an exported original is not a complete backup of app state. Automatic Android
backup is disabled for this app.

The Linux `uninstall.sh` removes the owned runtime and launchers while retaining
private application state. Removing a client does not restore stock firmware or
cancel an OTA request already submitted to Zigbee2MQTT. For interrupted work,
read [Troubleshooting](troubleshooting.md) before removing anything.
