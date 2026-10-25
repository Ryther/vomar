# Vimar 30805 research and custom firmware

Custom nRF52840 firmware, an Android updater and a Zigbee2MQTT converter for the
Vimar View Wireless Linea 30805 dimmer. The project replaces the radio-side
firmware while retaining the original secondary power-controller firmware.

Firmware **1.0.0 is a signed qualification candidate**. Its bounded standalone-DK
runtime trial passed, including authenticated BLE identity/hash checks, recovery
transitions, persistent fault diagnostics and exact restoration of the DK's
prior FLASH/UICR/FICR. Its thirteen physical qualification flags remain false;
this is not a qualified fleet release. Earlier Vimar update and stock-restoration
trials succeeded on their specific historical images and routes. They do not
qualify the new common first-install and restoration paths.

Android **1.0.0** retains the existing 0.6.5 interface and behavior, with release
version metadata updated. App and firmware versions and qualification are
independent. The app includes Bluetooth update trials, optional Zigbee2MQTT/MQTT
integration, and a reviewed phone → DK → target first-install flow. The complete
phone-driven first-install/repair/start route still needs physical qualification.

## Start here

- [Research summary and evidence limits](docs/research-summary.md): architecture,
  recovered interfaces, protection behavior and reproducible analysis.
- [Firmware builds and profiles](firmware/README.md).
- [Android updater](docs/android-updater.md), [first installation](docs/android-first-install.md)
  and [Bluetooth trials](docs/android-bluetooth-trial.md).
- [Zigbee2MQTT converter](integrations/zigbee2mqtt/README.md),
  [controls](docs/zigbee-controls.md) and [OTA](docs/zigbee-ota.md).
- [Known facts](docs/known-facts.md), [unresolved hypotheses](docs/hypotheses.md)
  and [research rules](docs/research-rules.md).

## Source and release artifacts

Git contains source, public documentation, public verification keys and synthetic
test fixtures. APKs, signed firmware ZIPs, OTA files and build outputs belong in
reviewed GitHub Release assets, with checksums and qualification scope. Their
presence or a valid signature alone does not establish hardware qualification.
This source checkout does not imply that a release has been published.

Original vendor APK/firmware, full device backups, network data, credentials and
private signing keys are excluded. Keep each device's original backup privately;
it is separate from a shared firmware release. Local `inputs/`, `analysis/`,
`experiments/` and `work/` retain evidence and generated output outside Git.

## Check the source

Use a Python 3 environment with `pytest`, `cbor2`, `cryptography` and `intelhex`,
plus Node.js and npm. From the repository root, run the self-contained host suites:

```sh
PYTHONPATH=. python3 -m pytest tools/firmware/tests tools/hardware/tests tools/android/tests
npm test --prefix integrations/zigbee2mqtt
```

Tests that require private original artifacts, archived native builds or an SDK
skip when those inputs are absent. A skipped hardware/artifact check is not a
qualification result. Firmware builds additionally require the pinned Nordic
SDK and a local signing setup; Android builds require Java 17 and the Android
SDK. See the component guides for these separate checks.

For static reverse engineering on Linux, install Git, Bash, Python 3, Ghidra
and the JDK required by your Ghidra version; put `analyzeHeadless` on `PATH`.
The [research summary](docs/research-summary.md#reproduce-the-static-analysis)
describes input validation and headless analysis. The optional
`./tools/helpers/check-env.sh` reports available research tools, including tools
unneeded for static analysis. With originals supplied and a local `analysis/`
directory created, `./tools/helpers/inventory-inputs.sh` records their hashes.
These helpers are separate from the public host suites. Local editor/container
configuration is not included in this source distribution.

Physical programming, erasure, bootloader changes and UICR writes require explicit
operator approval. Use an isolated bench arrangement for SWD work. See
[repository safety and evidence rules](AGENTS.md) before hardware work.
