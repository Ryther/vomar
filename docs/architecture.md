# Architecture

Vomar separates device firmware, package verification, operation ownership,
transports and user interfaces. It replaces the nRF52840 side of a compatible
Vimar 30805 while retaining the secondary power controller. Software output
state does not establish measured lamp output or complete electrical protection.

## Components and ownership

| Component | Responsibility | Boundary |
| --- | --- | --- |
| `firmware/src` and profile directories | MAIN behavior, settings, buttons, radio, recovery and restoration profiles | Hardware profiles and the DK simulator remain distinct. |
| `firmware/loader_contract` | Protected loader and permitted image/slot transitions | Signed finite loader contracts, not a downloaded filename, govern admission. |
| Android `core` and shared first-install contracts | Package, identity, operation and interrupted-session decisions | Native Android UI and adapters do not bypass these checks. |
| Android `app` | English interface, foreground operation lifetime, BLE, USB and broker adapters | Opening a screen or receiving metadata never grants mutation consent. |
| Desktop `core` | Package verification, retained state and operation contracts | Independent of GUI widgets and CLI argument parsing. |
| Desktop `service.py` | Compose the engine, private store and adapters | Own operation admission rather than implementing it again in each client. |
| Desktop `adapters` | BLE/SMP, probe/OpenOCD, MQTT, release downloads and OS credential storage | External responses are data; errors preserve uncertainty. |
| Desktop `gui` and `cli.py` | Present preview, request fresh review, report progress and Stop | Neither saved selection nor UI state is authorization. |
| `integrations/zigbee2mqtt` | Converter, supported controls and OTA integration | Generic OTA capability does not authorize a Vomar update. |
| `tools/firmware` | Shared signed-package validators plus firmware build/packaging helpers | Runtime validators are also imported by the desktop client. |
| `tools/release` | Distribution manifests, reports, signing assembly and GitHub draft publication | Build/test jobs and credential-bearing publication are separate. |
| `tools/dev`, `.devcontainer` | Reproducible development and optional SDK setup | No bootstrap step accesses physical hardware or installs an account credential. |

The source tree contains research helpers as well as product code. Sonar's
product scope includes firmware, clients, converter, firmware/package helpers
and the runtime-imported `tools/release/manifest.py`; it excludes release
orchestration, development and reverse-engineering helpers. Secret scanning
still covers all public files and reachable history. Build and dependency
audits remain required independently of product-quality metrics.

## Update and recovery decisions

1. Download or select a signed common package. Verify bounded archive contents,
   signature, roles, geometry and supported loader contracts before using it.
2. Read authenticated live target identity and state. A saved name, IEEE address,
   radio advertisement or release checksum is insufficient authorization.
3. Preview the exact package, target and operation. Explicit review grants only
   that operation. Stop, restart or an uncertain result requires fresh review.
4. Record intent before an admitted mutation and retain acknowledgments and
   uncertainty afterward. Transfer or reset acknowledgment is not proof that
   the lamp, radio or recovery works physically.
5. Preserve the original backup and journal across interruption. Repair must
   bind the same target, original and package; do not substitute a new capture
   for the original or automatically release an uncertain halted CPU.

First installation has a separate reviewed HALT, two byte-equal original reads,
private save/reopen, bounded FLASH installation and a separately reviewed
start. Android 1.0.6 offers an additional original export; desktop requires
its export/reopen contract. It never implies consent to erase, recover, rewrite UICR or replace a
bootloader. See [installation](installation.md) and
[the Android first-install contract](android-first-install.md).

## Persistence, privacy and concurrent work

Private application state retains settings, optional names, sessions and
originals. Broker passwords belong to the OS credential store on desktop and
Android's encrypted private storage. They are not release assets. Ordinary
uninstall and removal of an optional saved device are distinct from deliberate
deletion of recovery material.

The shared engine owns admission and cancellation. BLE work is serialized;
fleet scheduling also limits work per Zigbee network. A Zigbee request already
submitted to Zigbee2MQTT may continue after the local client stops, so uncertain
remote work requires explicit reconciliation. The
[desktop guide](desktop.md) describes these user-visible consequences.

## Development, checks and release ownership

The [Dev Container](development.md) provides tools without household services.
Tests use synthetic packages, disposable brokers and transport doubles. Real
BLE/USB behavior and physical qualification are separate evidence.

Release Please proposes the distribution version and changelog. Firmware,
Android and other components retain their native version owners. The release
pipeline validates one exact source SHA, assembles signed artifacts through
protected jobs, checks the complete draft and uploaded bytes, and publishes
only after all matching gates pass. The publisher preserves identical existing
assets and rejects differing ones. See [releasing](releasing.md).

PR Sonar scans Python, JavaScript and Kotlin with real coverage and findings;
firmware C has the separate mandatory CodeQL check. Full protected main/release
Sonar includes C compilation and coverage. The PR report is not a substitute
for that full exact-candidate release gate.

The [research summary](research-summary.md) records confirmed observations,
inferences and hardware limits. It does not turn the current firmware candidate
into a physically qualified distribution.
