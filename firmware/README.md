# Vimar 30805 firmware

The nRF52840 application implements Zigbee On/Off and Level Control, configurable
local gestures, timer and power-on policy, layered LED behavior, persistent
settings, fault diagnostics and manufacturer cluster `0xFC00`. A separate DK
simulator supports development without the Vimar power stage. The Vimar adapter
uses recovered PWM/GPIO behavior and a conservative candidate P0.31 protection
monitor; it does not report physical lamp measurements or power-stage
acknowledgement. Electrical protection coverage remains unresolved.

Firmware **1.0.0 is a signed qualification candidate**. Its bounded standalone-DK
runtime/recovery trial passed and the DK's prior FLASH/UICR/FICR were restored
exactly. All thirteen physical qualification flags remain false. Earlier exact
images passed DK OTA/power-interruption trials, Vimar updates and a dedicated
stock-restoration trial. Those results do not qualify the new common first-install,
generic restore or complete 1.0.0 update routes. See the
[research and evidence summary](../docs/research-summary.md).

## Connection selector and Zigbee pairing

The feature-branch implementation adds a five-second two-button selector, bounded
two-minute Zigbee pairing and an explicit authenticated Bluetooth request. See
[Connection modes](../docs/connection-modes.md) for exact colours, network replacement,
timeouts and compatibility/qualification limits. It needs matching MAIN/recovery;
its source presence does not change qualification of the existing 1.0.0 package.

## Build dependencies

[west.yml](west.yml) pins nRF Connect SDK `v3.4.0` and Nordic Zigbee R23 add-on
`v1.4.0`; the development environment uses Zephyr SDK `v1.0.1`. From the repository
root, bootstrap into ignored local storage:

```sh
python3 -m venv work/ncs-venv
. work/ncs-venv/bin/activate
pip install west
west init -l "$PWD/firmware" work/ncs-workspace
cd work/ncs-workspace
west update
west zephyr-export
west packages pip --install
west sdk install --version 1.0.1 --gnu-toolchains arm-zephyr-eabi
```

Use the repository's absolute `firmware` directory as the application source if
your west workspace is elsewhere. Builds need a matching local signing setup;
only the public research key is distributed. See [key handling](keys/README.md).
An independently generated key creates a different trust root and does not sign
updates accepted by devices using this project's existing public key.

## Profiles and outputs

The base BLE profile, Zigbee DK simulator and independent-recovery profile are
separate build configurations. From `work/ncs-workspace`, build without device
access:

```sh
# Base BLE profile
west build --sysbuild -b nrf52840dk/nrf52840 ../../firmware \
  --pristine -d ../build-ble-dk

# Zigbee DK simulator
west build --sysbuild -b nrf52840dk/nrf52840 ../../firmware \
  --pristine -d ../build-zigbee-dk -- -DEXTRA_CONF_FILE=zigbee_dk.conf

# Independent BLE recovery and Zigbee main
west build --sysbuild -b nrf52840dk/nrf52840 ../../firmware \
  --pristine -d ../build-ota-zigbee-dk -- -DFILE_SUFFIX=ota
```

The opt-in `ota` profile uses an independent signed BLE updater, selected by DK
Button 1 during reset or an invalid primary image. It advertises as
`Vimar30805-Rescue` and uses authenticated SMP. The fixed development pairing
code `824005` is public research configuration, not a production credential.
This single-primary-slot profile offers independent recovery; it does not keep
a previous application image for automatic rollback. A hung signed application
can require the reset/recovery trigger. No Vimar recovery pin mapping follows
from the DK button mapping.

From the repository root, validate the generated recovery profile:

```sh
work/ncs-venv/bin/python tools/firmware/validate_recovery.py \
  --build-dir work/build-ota-zigbee-dk \
  --imgtool work/ncs-workspace/bootloader/mcuboot/scripts/imgtool.py \
  --key firmware/keys/dev-public.pem
```

The merged HEX includes loader/recovery/application and belongs to initial
provisioning. It is not an application-update file. An ordinary BLE update uses
the signed application or matching DFU ZIP; compressed Zigbee OTA uses its own
signed carrier and matching installer. Build outputs belong under ignored
`work/` or `experiments/`, not Git.

## Hardware application and common packages

The [BLE research application](research/README.md) supplies authenticated
instrumentation and the recovered PWM/GPIO backend. The main Vimar adapter is
[src/platform_io_vimar.c](src/platform_io_vimar.c). Current common packages bind
MAIN, recovery, migration, loader and restoration helpers through protected
role/profile metadata, exact hashes and finite loader contracts. The candidate
builder is [build_typed_common_candidate.py](../tools/firmware/build_typed_common_candidate.py);
its native builds require a prepared local SDK and signing environment.

The current schema3 candidate is shared by compatible devices; originals and
transaction checkpoints stay private and device-specific. Ordinary fleet and
release validators reject qualification candidates. Initial phone/DK installation,
explicit interrupted-install repair and a separate verified start are documented
in [the Android installation guide](../docs/android-first-install.md).

The original [dedicated restore gate](restore_gate/README.md) and the newer
[common restore engine](common_restore/README.md) have different evidence scopes.
A historical full Vimar stock restore succeeded with the dedicated path; the
new common-loader/generic helper route remains physically unqualified and has
no operational stock-restoration UI in the current Android app. Carrying signed
helpers does not make that user workflow available.

See [Zigbee OTA](../docs/zigbee-ota.md), the
[Zigbee2MQTT converter](../integrations/zigbee2mqtt/README.md) and
[loader contracts](loader_contract/README.md) for their respective interfaces.
Physical programming, bootloader writes, erasure and UICR writes require explicit
operator approval; the commands above only build and inspect local files.

## Host checks and optional local integration checks

From the repository root, with the Python dependencies listed in the
[main README](../README.md), run:

```sh
PYTHONPATH=. python3 -m pytest tools/firmware/tests -rs
```

Portable unit and host-C tests stay active in a public checkout. Tests consuming
absent private originals, archived exact images/manifests, a matching local
private signing key or native SDK artifacts skip only their dependent cases;
`-rs` shows the missing-input reasons. Never publish the matching private key
to make such a test run. SDK-dependent checks cover actual imgtool/zcbor,
compression decoding and reviewed ZBOSS headers; set `VIMAR_NCS_WORKSPACE` for
a prepared local SDK workspace. These optional checks and historical artifact
checks remain separate from physical qualification.

## Wired auxiliary push-button candidate

The source now includes the previously omitted wired-input path. Conventional
push buttons connected to terminal P share one auxiliary input; they are separate
from front UP/DOWN buttons and from Bluetooth Mesh/radio accessories. The stock
Zigbee trace uses a pulse-qualified input and one-button dimmer behavior. The
candidate provides short-press toggle, long-press dimming while already ON,
alternating direction after long release, and stop on release. Configured level
limits, hold timing, step size, auto-off and output protection still apply.

A button held at startup, through connection selection or across an external
command must release before another action. Auxiliary presses never enter the
connection selector. They do not masquerade as front UP/DOWN gesture events or
add a new persistent setting. Mesh scene assignment and radio accessory pairing
are separate features and are not implemented by this change.

On one installed Vimar running the exact signed MAIN 1.1.3 candidate, the
operator reported successful short toggle, long-press dimming, release-to-stop
and alternating direction with all four wired buttons. The preceding OTA and
correlated readback verified the version, unchanged recovery and all 40 settings.
This is bounded operator-observed acceptance; no terminal waveform or physical
MAIN hash was measured, and broader hardware/release qualification remains open.

## Front holds, phase-cut selection and Identify (schema 8 candidate)

A front UP or DOWN long press dims only a lamp that is already ON with an
applied ON output. Holding either button while OFF keeps it OFF, including
an initial ON delay or an unfinished OFF ramp. The release does not become a
short click. The separate wired auxiliary input keeps its existing behavior.

`phase_cut_mode` selects `trailing_edge` (TE, wire value 0) or `leading_edge`
(LE, wire value 1). The default is TE, including migration of older records without a phase field.
An explicit `CONFIG_RESEARCH_STOCK_CONFIG19=1` build override selects LE.
The selection uses P0.19 while retaining the stock secondary power controller.
A change requires accepted, target and applied output to be OFF with no pending
delay or ramp. It is saved durably before applying the GPIO; a storage failure
leaves the mode unchanged. An unexpected hardware apply failure inhibits output
and reports an output fault. No automatic retry or restart is performed.

Settings record v5 appends the phase choice and reads v1–v4 without discarding
their values. Older firmware cannot decode v5: a downgrade is not a settings
migration and must not be assumed to preserve configuration. Warm recovery
returns preserve P0.19; cold starts load the saved choice before enabling output.

The standard Identify command controls a temporary green LED flash at 5 Hz.
The converter's Identify button requests 15 seconds; IdentifyTime=0 cancels it.
A fault indication has priority. On expiry the configured LED profile or an
unexpired manual override returns. Identify never changes the lamp or saves LED
configuration. Repeating Identify during an active SDK countdown can shorten
the renewed interval by less than one second.

These behaviors have host-test coverage. Electrical phase-cut behavior,
load compatibility and mounted-device timing still require physical validation;
software tests alone do not qualify this candidate.
