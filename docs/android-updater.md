# Android app

Use Vomar to organize dimmers, connect to Zigbee2MQTT, inspect firmware and review
updates on Android 8.0 (API 26) or later. The app's identity is
`org.openvimar.updater`; its version appears in **Settings**. App, firmware and
bundle versions are independent.

## Install and track with Obtainium

**[Install Vomar with Obtainium](https://apps.obtainium.imranr.dev/redirect?r=obtainium://app/%7B%22id%22%3A%22org.openvimar.updater%22%2C%22url%22%3A%22https%3A%2F%2Fgithub.com%2FRyther%2Fvomar%22%2C%22author%22%3A%22Ryther%22%2C%22name%22%3A%22Vomar%22%2C%22additionalSettings%22%3A%22%7B%5C%22apkFilterRegEx%5C%22%3A%5C%22%5Evomar-android-%5B0-9%5D%2B%5C%5C%5C%5C.%5B0-9%5D%2B%5C%5C%5C%5C.%5B0-9%5D%2B%5C%5C%5C%5C.apk%24%5C%22%2C%5C%22releaseTitleAsVersion%5C%22%3Atrue%2C%5C%22versionExtractionRegEx%5C%22%3A%5C%22%5C%5C%5C%5CbAndroid%5C%5C%5C%5Cs%2B%28%5B0-9%5D%2B%5C%5C%5C%5C.%5B0-9%5D%2B%5C%5C%5C%5C.%5B0-9%5D%2B%29%5C%5C%5C%5Cb%5C%22%2C%5C%22matchGroupToUse%5C%22%3A%5C%22%241%5C%22%2C%5C%22versionDetection%5C%22%3Atrue%2C%5C%22includePrereleases%5C%22%3Afalse%2C%5C%22includeDrafts%5C%22%3Afalse%2C%5C%22trackOnly%5C%22%3Afalse%7D%22%7D)**

1. Open the link on your Android phone. If Obtainium is missing, the redirect
   page offers its installation first.
2. Review the Vomar configuration and confirm the import.
3. Run an update check in Obtainium, then confirm installation of the signed APK.
   Review Android's installer-source permission if requested.
4. Open Vomar → **Settings** and check the installed Android version.

Already installed from an APK? **Install over it. Do not uninstall or clear app
data.** Android checks package ID and signing continuity. A signer error needs
investigation, not deletion of originals or session records.

Obtainium reads the **Android component version** from the release title. For
example, **Vomar bundle 1.0.0 · Android 1.1.4** reports Android `1.1.4` / code `34`,
not bundle `1.0.0`. The publisher derives that title from the verified release
manifest. A later firmware-only bundle does not become an Android update. OS
version detection stays enabled so APK installations outside Obtainium can be
recognized.

The [import configuration](../apps/android-updater/obtainium.json) uses the
standard GitHub source with **Use release title as version** and an Android-only
version extraction rule. No account/token is needed, subject to GitHub's
anonymous API limits. Import the complete configuration: a plain repository URL
alone uses the bundle tag. Keep OS version detection enabled.

If you imported the older bundle-tracking configuration, open the install link
again and confirm the import. It replaces Vomar's Obtainium tracking settings;
**the installed Vomar app and its data remain in place**. Run a fresh update
check afterward. You do not need to remove the tracking entry or uninstall Vomar.

Immediately after import, **Unknown Latest**, **placeholder**, or **Last update
check: Never** can appear until the first successful source check. If checking
fails, inspect that error rather than uninstalling. See
[Obtainium troubleshooting](troubleshooting.md#obtainium-shows-an-unknown-or-wrong-version).

## Devices

Open **Devices** to inspect a saved dimmer, add a nearby Bluetooth device or
import Zigbee devices from a connected broker. Names and rooms are optional
organization; a radio name is not authenticated device identity.

Tap a row's name, version or central area for details. The checkbox selects a
device for a group; the status indicator explains update eligibility. A reported
firmware version marked **(saved)** is historical and may be stale.

### One dimmer across Bluetooth and Zigbee

After first installation, Devices retains the UID and original-backup link.
Connect the broker and include the dimmer's Zigbee2MQTT base topic. Once every
configured topic has reported its inventory, an unambiguous identity match can
attach Zigbee to the same record. If one topic is unavailable, use explicit
**Add device → Import from Zigbee**.

Existing room, Bluetooth address and original remain associated. Matching names
alone never merge devices. In **Edit name and room**, select **Use Zigbee name**
to follow the broker name, or clear it for a custom name. A Bluetooth address
is recorded from an observation, never inferred from an IEEE address.

## Automatic Zigbee2MQTT connection

1. Open **Settings → Zigbee2MQTT** and save the broker profile and named topics.
2. Choose **Connect** and check that the expected inventories appear.
3. Save edits to the active connection with **Save and reconnect**.

One broker can be active, with up to three Zigbee2MQTT base topics. Credentials
are encrypted in Android private storage. An unencrypted local transport needs
its separate consent; a port number alone does not enable TLS.

After activation, reopening the app restores that connection and subscriptions.
Temporary network loss shows **Reconnecting**. **Disconnect** disables automatic
restoration until you choose Connect again. Saving a profile alone does not
activate it. Credential/certificate/configuration failures stop retries; correct
the settings or use **Retry connection**. This is not a permanent background
service after Android stops the process.

Reconnection restores subscriptions only. It never replays device commands,
starts firmware work or reconciles an uncertain operation automatically.

## Project releases and experimental firmware

Use **Settings → Firmware updates → Check for updates** for the configured
GitHub source. **Project release VERSION is available** announces a published
bundle. **Firmware NATIVE_VERSION · Experimental** identifies its firmware's
status. **Open release notes** opens that exact release.

This notice is metadata, not a verified firmware download or permission to
install it. For an experimental trial, read the known issues, download the
candidate ZIP and use **Devices → dimmer → Update firmware → Choose firmware**.
**Updates → Choose local ZIP…** accepts qualified packages. Checking for a release
preserves a previously selected qualified package and starts no fleet or OTA job.

A draft is not a published release. The public trust anchor verifies firmware
independently of the download source. See [packages and backups](offline-guide.md).

## Update one dimmer

For a dimmer already running compatible Vomar firmware, use
**Devices → device → Update firmware**. Choose the package, inspect the live
target, review its identity and target version, then confirm that operation.
Keep the phone nearby and use the visible Stop action if needed.

Follow [the Bluetooth procedure](android-bluetooth-trial.md) for exact steps,
legacy recovery limits, interruptions and report export. Device pairing with a
new Zigbee network is separate: [Connection modes](connection-modes.md).

## Activity and groups

Activity retains operation progress, acknowledgments and uncertain outcomes.
Open the relevant device/group before resuming interrupted work. A restarted app
restores records, never approval or a running device operation.

Fleet scheduling supports sequential work and bounded network parallelism, with
one global Bluetooth operation and one Zigbee operation per network. Only
qualified, compatible targets/packages pass automatic admission. The presence of
an experimental release or a generic OTA capability does not enable fleet work.
An OTA request already submitted to Zigbee2MQTT may continue after local Stop;
read-only reconciliation is required before another operation on that network.

## Tools and private originals

**Settings → Tools → First installation** is the separately reviewed USB/DK bench
flow. It captures two matching complete originals, saves and reopens the archive
privately, installs bounded FLASH and ends halted. Starting verified firmware is
another reviewed action. See [First installation](android-first-install.md).

**DK tools** is a separate read-only monitor and backup tool. A monitor stops when
backgrounded and never restarts itself. **Read recovery history**, where supported,
is an explicit read-only Bluetooth diagnostic with optional private JSON export;
it is not an automatic step in an update.

Keep originals, journals and diagnostic exports private. Use
**Devices → device → Original firmware** to export a retained original.
Uninstalling or clearing storage deletes private copies and credentials; keep
independent exported originals permanently. An exported report is not an original
firmware backup and is not a complete export of app state.

## Problems and support

Use [Troubleshooting](troubleshooting.md). Report the app/OS versions, package
version, last phase and sanitized error. Do not publish originals, passwords,
raw network captures or full device identities. An acknowledged reset is not
proof of working lights, radio or recovery.

Developers: [Android checks and local builds](development.md#android-checks-and-local-builds),
[interface reference](android-updater-ui.md), [wording rules](android-updater-language.md)
and [qualification evidence](ux-evidence.md).
