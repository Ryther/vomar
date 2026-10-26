# Install, configure and update Vomar

Start with the client, without connecting a probe or approving a device write.
Vomar's current firmware 1.0.0 is a qualification candidate with thirteen physical
checks pending. Ordinary release/fleet routes reject candidates. Use a separately
authorized qualification procedure when evaluating a candidate; installing the
client does not authorize that procedure.

## Before downloading

- Choose Android or the native desktop package for your OS and architecture.
  Desktop targets are Linux x64, Windows x64, macOS Intel and macOS arm64;
  target contracts and platform limitations are in [Desktop](desktop.md).
- Obtain artifacts from a reviewed project distribution. Check its version,
  source commit, component versions, qualification scope and `SHA256SUMS`.
  The repository and its badges do not prove that a distribution is published.
- Preserve the device's original backup privately, independently of shared
  firmware. Client installation needs neither a device registry nor a Nordic SDK.
- For Bluetooth use, the OS must support the selected adapter and grant the
  app's requested Bluetooth permissions. USB/DK access is needed only for the
  separately reviewed bench path.

If no suitable published distribution is available, stop at source development
or an authorized qualification exercise. Do not rename a candidate to make it
look like a stable release. The GitHub source setting is
`https://github.com/Ryther/vomar`; local signed ZIP selection remains available
without a GitHub account.

## Install the Android client

1. Obtain the signed APK for the intended app version and verify its distribution
   checksum. App and firmware versions are independent.
2. On the phone, open the APK through the system installer. If Android requests
   permission for that installer source, review and grant it deliberately.
3. Open the app. Devices and Settings should be available without a broker or
   a connected dimmer. Check the installed app version in Settings.
4. In Settings → Updates, select the intended signed common firmware ZIP or
   configured release source. Package verification alone starts no write.
5. Grant Bluetooth permissions when using a Bluetooth action. An optional
   Zigbee2MQTT connection is configured separately under Settings → Zigbee2MQTT.

A signed upgrade must preserve package identity and signing continuity. Do not
uninstall merely to bypass an Android signature mismatch: preserve private state
and investigate the selected APK. See [Android](android-updater.md) for current
client behavior and [troubleshooting](troubleshooting.md).

## Install the desktop client

Use the package instructions in [Desktop → Install](desktop.md#install):

- **Linux x64:** extract the downloaded archive into a new directory. From that
  directory run `sh Vomar/install.sh`. Launch Vomar from the desktop menu, or use
  the installed `vomar-gui` and `vomar` launchers under `~/.local/bin`.
- **Windows x64:** run the per-user installer or extract the portable ZIP.
  Review the normal first-launch approval for the unsigned desktop application.
- **macOS:** choose the matching Intel/arm64 DMG and copy Vomar to Applications.
  The current packaging uses ad-hoc signing, without trusted developer signing
  or notarization; review the normal OS approval rather than disabling platform
  protection globally.

Open the app without a device attached. Devices, Activity and Settings should
appear. Desktop users do not install Python or SDKs. `vomar --version` and
`vomar --help` check the installed CLI without starting a device operation.

In Settings → Updates, select the signed common ZIP or release source. Preserve
the ZIP as a package: desktop ZIP assets are installers, while the canonical
firmware ZIP is selected by role and verified content. See the
[offline package and recovery checklist](offline-guide.md).

## Optional broker configuration

Use a broker and Zigbee2MQTT environment you control. Desktop credentials use
the OS credential store; Android uses encrypted private storage. One active
broker may serve up to three configured Zigbee2MQTT base topics. Broker login,
topic selection and saved device names never approve firmware work.

For plaintext local connections, review the separate consent. Use the exact
broker port and a client-supported transport. Connect explicitly and check the
connection result before interpreting device metadata. Saved/retained readings
may be stale and are not authenticated update eligibility. See
[Android](android-updater.md) or [Desktop](desktop.md#optional-mqtt-and-fleet).

## First use and observable success

Client installation succeeds when the selected app opens and reports the
expected app version. Package inspection succeeds when the app accepts the
signature, roles and compatibility contract. Neither result proves a working
device or authorizes a write.

For an existing compatible custom target, use its explicit review flow and
confirm live identity before deciding on an update. Qualification-candidate
Bluetooth trials and initial bench installation are separate procedures:
[Bluetooth trial](android-bluetooth-trial.md) and
[first installation](android-first-install.md). Physical intervention requires
the operator's separate approval; do not start it from an installation check.

## Upgrade or remove a client

Read the release's migration notes, preserve private originals and sessions,
then install the matching signed Android upgrade or replacement desktop package.
Reopen the client and verify the installed app version and retained state.
Installing a newer client does not install newer firmware automatically.

The Linux bundle's `uninstall.sh` removes its owned runtime and launchers while
preserving private application state. Android uninstall can remove app-private
state: export originals and required records before proceeding. Do not assume
that an exported original is retained merely because it was once captured.
Removing a client does not restore stock device firmware or cancel an already
submitted remote OTA operation. Use [troubleshooting](troubleshooting.md) before
changing anything when a session is interrupted or uncertain.
