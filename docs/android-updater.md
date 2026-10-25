# Vimar Updater Android 1.0.2

App 1.0.2 (versionCode 22) fixes stale metadata for saved Zigbee devices. While
the selected MQTT connection is active, device-topic firmware reports update
Devices and the saved record automatically. A stale bridge inventory cannot
replace a version already reported on the device topic. For the known OpenVimar
wire format, the installed OTA version is decoded; the available/latest version
is never shown as installed firmware. Local device names and rooms are retained.

Saved readings are labelled `(saved)` when disconnected or when only cached
broker data is available. Device details show when the version information was
received. Opening the app still does not automatically connect, query or update
devices; receiving MQTT metadata never authorizes a firmware operation.

App 1.0.1 (versionCode 21) delivers the approved saved-connection and device-filter
changes. Settings → Zigbee2MQTT now supports multiple named saved broker profiles,
one active connection, a separate named Zigbee topics list and saved-credential
editing. Add device displays topic names. Devices → Show uses one native list
for continuous press/drag/release, normal tap, keyboard and accessibility, without
the previous Use list mode switch or Done step.

The signed APK is delivered locally under
`experiments/android-updater/releases/1.0.2/`. Its incremented version code and
existing release signer support upgrading the installed 1.0.0 app. Package ID,
firmware trust key and permissions remain unchanged. Firmware versioning and
qualification remain independent. Native gesture/accessibility and live-broker
acceptance are still separate from the software build and APK audits.

App0.6.5 completed the approved operation-clarity pass: persistent Bluetooth
target/phase, actionable MQTT failures and inline field errors, non-secret
network drafts, return-to-origin navigation, compact Activity groups and truthful
completion counts, package/source disclosure and one filter selector at a time.
No update approval, signature, identity or resume gate is restored from UI state.


App0.6.4 groups advanced tasks under **Settings → Tools**: first installation,
read-only DK tools and Bluetooth trial. Normal device and fleet updates remain
in the primary flow. MQTT accepts bare host:port (for example
`broker.example:1833` → `tcp://broker.example:1833`), with the
exact port preserved and explicit consent for unencrypted local connections.
Address, topic and username fields use technical keyboards without automatic
capitalization or correction; passwords remain masked. Trial status and Stop
stay accessible while scrolling.

Android0.6.1 added **Settings → Tools → Bluetooth trial** for one explicitly reviewed
signed qualification candidate on an already-custom mounted dimmer. It reuses
the existing recovery migration and update engines under the shared BLE lease,
with a separate private candidate selection, foreground lifetime, Stop and
report export. Normal release, fleet and Zigbee routes still reject candidates.

For exact phone steps, see [Update a mounted dimmer by Bluetooth](android-bluetooth-trial.md).
The app version is 1.0.2. Firmware packages have independent versions and
qualification records.

App0.6.3 explicitly queues the initial system pairing request after LE service
discovery and before McuMgr's protected notification setup. This uses the pinned
Ble2.11 supported legacy init queue because McuMgr2.7.4 makes `initialize()`
final. Existing bonds are never removed and no automatic pairing retry is added.
The real0.6.2 Android16 report established LE/MTU247 success, then disconnect22
after notification setup was requested, without observed pairing events. The
subsequent owner-reported legacy-bridge phone trial succeeded within its bounded
scope; pairing on other source/recovery combinations remains a separate check. The exact old REC0.7.1 build also
permits only one bond; its current occupancy is unproven, so this firmware
constraint may require an already bonded client's intervention separately.

Prior app0.6.2 fixes missing Bluetooth diagnostics in **Save trial report**. Reports
freeze the inspected attempt before releasing the radio lease, and include
Android/app versions, observed bond state and whitelisted native connection,
MTU and notification metadata. PINs and raw packet/CBOR logs are not retained.
That early Android16 disconnect is historical evidence; later phone success
does not establish its exact cause or every supported pairing combination.

The native app uses the approved English interface: anthracite, orange and teal,
with light, dark and system themes. Devices, inline Activity groups and Settings
remain the main destinations; Updates and the optional MQTT connection are in
Settings, with advanced tasks grouped under Tools. Device names, rooms and fleet registration are optional organisation,
not identity files or update authority.

## Implemented software

- The current common schema3 ZIP serves compatible devices without per-device
  update packages or a manually maintained UID/IEEE/MAC registry. Its signed
  manifest binds model, layout, components, typed finite loader compatibility
  and the separate first-install descriptor. Schemas1/2 remain compatible with
  their existing identity rules; old packages do not gain schema3 authority.
- Common components require the pinned ECDSA key, protected role/profile, strict
  TLVs and slot bounds. Identity-capable targets supply live authenticated
  identity and loader measurements before mutation; the legacy bridge uses the
  separate exact-image gates below until identity adoption. Device-specific
  checkpoints remain private.
  Ordinary updates select MAIN and, when necessary, MIGRATION; the presence of
  signed stock-restoration helpers does not add a stock-restoration UI.
- Add device searches the project capability service and reads live identity
  before optional naming. Legacy SMP-only targets remain unverified until exact
  signed recovery/source-image and authenticated-connection gates pass. The
  legacy bridge uploads only the common self-authorising MIGRATION, records
  restart intent and requires explicit confirmation after an uncertain restart.
- Activity expands each batch inline. The All filter uses a wrapping vertical
  wheel with Done/Cancel and an accessible list alternative. A durable queue
  supports sequential operation, or one Zigbee operation per network plus one
  global Bluetooth connection. Interrupted work requires explicit resume.
- Stable GitHub release ZIPs download over HTTPS into private verified storage;
  the configured default is `https://github.com/Ryther/vomar`. An editable source
  and local ZIP remain available. The public trust anchor is independent of the
  download source. No GitHub token is requested, and missing published releases
  do not block local files.
- Optional MQTT supports one broker and up to three exact Zigbee2MQTT topics.
  AndroidKeystore-encrypted credentials are excluded from backups and reports.
  Supported custom/stock devices can be imported; the bridge/devices JSON-file
  alternative remains available. Zigbee OTA requires a signed carrier, its exact
  verified HTTPS bytes and a fresh advancing compatibility observation matching
  the release recovery digest. A generic `ota` flag grants no update authority.
- **Settings → Tools → First installation** implements phone → USB → DK → target capture,
  export/reopen, reviewed installation and a separate verified start. It halts
  the exact CPU, compares two complete FLASH/FICR/UICR acquisitions, keeps one
  private original ZIP, and requires successful export and exact same-document
  reopen before any FLASH intent. Durable journals precede bounded writes; the
  anchor commits last. UICR is preserved. A successful install ends halted.
- Interrupted first installations have an explicit repair path using the same
  signed release, target and protected original. A byte-identical original ZIP
  may move to another Files/cloud URI. Fresh preview and confirmation are
  mandatory. Repair verifies only, writes a missing final commit, or rebuilds
  the bounded image and commits last. The greatest issued mutation scope is
  retained across attempts; never-issued pages must still match the original.
  Prior uncertainty prevents automatic CPU release. Unconfirmed HALT or lost
  transport remains reported as uncertain. No process restart restores approval
  or work.
- A signed `paused-reset-before-main-v1` first-install capability can admit the
  examined bounded watchdog profile that pauses on HALT. The app neither feeds
  nor resets it during backup. After explicit verified start, the new loader
  waits for one genuine watchdog reset before ordinary boot. Older releases
  without that signed capability still require an inactive watchdog.
- **Read recovery history** is an explicit read-only Bluetooth diagnostic for
  firmware implementing SMP group `0x8041`. It needs no update ZIP, checks live
  identity before and after the read, saves a bounded private result and offers
  an exact JSON export. New firmware provides this history; old firmware may
  report unsupported. Normal updates never query it automatically. Reset flags
  and recorded requests do not establish a physical reset cause or user action.
- **Settings → Tools → DK tools** remains separate and read-only: USB diagnostics, SWD
  identity, a changing monitor status and two-pass verified backup with explicit
  ZIP export. It does not invoke First installation. Its monitor stops on
  background/rotation and never restarts itself. Reports contain observations
  and bounded hashes, not acquired memory bytes.

The complete first-install and repair sequence is in
[First installation with Android and the DK](android-first-install.md).
The app retains a private immutable original and transaction evidence; the user
keeps its one exported original ZIP privately. A common release ZIP, a device's
original ZIP and an optional diagnostic report serve different purposes.

## Legacy Zigbee preparation for Bluetooth

A compatible MAIN0.5.5/REC0.7.1 device with an occupied one-bond table needs the
prepared0.6.3 intermediate before the Android trial. See
[Legacy Zigbee bridge](legacy-zigbee-bluetooth-bridge.md). The existing APK0.6.3
accepts the new common0.6.3 candidate; an APK rebuild is not required. The
intermediate and replacement recovery retain candidate status. A later
owner-reported Bluetooth update was corroborated by post-trial radio diagnostics;
full current-release migration/pairing qualification remains separate.

## Release artifacts and qualification

Android 1.0.2/code22 delivers the metadata refresh correction with the existing
package ID and release signer. Its release folder records the fresh test results,
signature/content checks and limits. No live broker or phone was used to diagnose
the reported bathroom value; the actual installed version remains unverified by
this app task. A broker/device must report a new version before the UI can show it.

Android 1.0.1/code21 includes the new UI implementation rather than only version
metadata. Its local release folder contains the signed APK, checksum, build
report and verification record. Fresh checks passed 437 JVM tests, 27 build-tooling
tests, lint and signature/content audits. The signing certificate matches 1.0.0,
and the new UI classes/labels are present in the signed DEX. No native runtime,
physical phone or live-broker acceptance is claimed for 1.0.1.

Android 1.0.0/code20 was prepared and delivered locally with the existing package
ID, signer and firmware public key. Every DEX/resource/asset matches 0.6.5; the
manifest version and signature metadata differ. Fresh verification passed 431 JVM
tests, 27 relevant build-tooling tests, lint, signature/content audits and six
bounded API35 software-emulator checks on the signed APK installed over 0.6.5.
Earlier 0.6.5 native/display checks remain historical evidence. Software-emulator
results do not qualify phone USB/BLE, the lamp, or physical recovery.

Firmware 1.0.0 is a separate signed common qualification candidate. Its bounded
standalone-DK runtime/recovery trial passed, followed by byte-exact restoration
of the DK's original state. All thirteen signed physical qualification flags
remain false. Normal release/fleet routes reject it; use only the explicitly
reviewed candidate route for its supported compatibility scope. The earlier
0.6.x candidates remain historical artifacts with their own exact bindings.
See [current firmware evidence and limits](research-summary.md).

Earlier physical evidence includes Android USB/SWD identity reads through a DK,
Vimar common-firmware updates with preserved settings/network return, and an
owner-reported Android Bluetooth update corroborated by subsequent radio
observations. These successes do not establish full phone-driven original
capture/export/reopen, first installation, interrupted-install repair and
verified start, nor the new common generic stock-restoration route. The current
app carries signed helper metadata but provides no operational stock-restoration
UI. A successful historical dedicated Vimar stock restore is separate evidence.

Git distributes source and public trust anchors. APKs, signed common ZIPs,
checksums and bounded qualification notes belong in reviewed GitHub Release
assets. No published release is implied by a local build. Build attempts and
local delivery folders stay under ignored `experiments/android-updater/`; never
overwrite a delivered version with different APK bytes. Private originals,
transaction journals, device identities and diagnostic reports are not release
assets.

## Reproduce the Android checks and build

Java 17 and Android SDK API35 are required. The checked-in Gradle wrapper and
strict dependency verification pin the build dependencies. With dependencies
available, run from `apps/android-updater`:

```sh
./gradlew :core:test :app:testReleaseUnitTest :app:lintRelease :app:assembleRelease
```

These are source/build checks, not physical phone tests. A clean environment
must obtain the pinned dependencies before an offline build can succeed. Host
packaging checks are separate and run from the repository root:

```sh
PYTHONPATH=. python3 -m pytest tools/android/tests tools/firmware/tests/test_package_android_update.py
python3 tools/android/build_updater.py --help
```

The local build helper uses the prepared Android/Java environment and offline
cache, runs tests/lint/assembly, then aligns, signs and audits the APK. It writes
new timestamped outputs under `experiments/android-updater/`; it creates no
firmware bundle. Release signing requires a private local Android keystore and
password file under `work/private/android-updater/`. The public checkout cannot
reproduce the existing release signature without that private identity. Preserve
it privately for app upgrades; it is separate from the firmware signing key.

The APK includes only the firmware public DER trust key, matching
`firmware/keys/dev-public.pem`. Changing download source does not change that
trust anchor. Content audits reject debug builds/signers, fixture trust anchors,
unexpected bundled firmware and PEM private-key markers. These bounded checks
are not a general proof against every possible secret. Runtime licenses are in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) and the
APK asset `third_party_notices.txt`.
