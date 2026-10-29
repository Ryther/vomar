# BLE research firmware

This page describes the historical BLE research application and its opt-in
profiles. For the common firmware architecture and the scope of earlier successful
Vimar trials, see the [public research summary](../../docs/research-summary.md).
Build-only statements below describe the original candidate stage.

Separate BLE-only application for the existing independent-updater flash layout.
The normal Zigbee application remains available under `firmware/`. This research
application keeps Bluetooth available while diagnostic commands are being tested;
Zigbee is not running concurrently.

## What is implemented

- Authenticated GATT diagnostic service `fde30805-c001-4a40-8d00-308050000001`.
- Typed status, signed native-level and independent-recovery requests.
- Default simulated backend, identified explicitly in every response.
- Optional stock-output reconstruction: PWM1 channel3/P0.13 at 7812.5 Hz,
  P0.14 enable-like behavior, initial output-low configuration of P0.11/P0.20,
  and compile-time P0.19 configuration. See the [recovered interface summary](../../docs/research-summary.md#recovered-stock-interfaces).
- Both local buttons held for five seconds request recovery, when built with
  matching software-recovery support. Bootloader UP/B1 entry remains separate.
- A recovery-pending latch rejects further output commands before shutdown/reset.
- Bounded DMA-completion polling; a timeout clears P0.14, latches output fault
  and rejects further level commands until reboot. This is a peripheral timeout,
  not a proven secondary-MCU or load protection mechanism.

Status `level` is the **requested native level**, not measured light output.
`off` uses -32768; `on` uses32767; `level 0` is the middle native level, not OFF.
These names do not establish lamp brightness or downstream electrical polarity.

## Build only

From the repository root, using the pinned SDK environment:

```sh
work/ncs-venv/bin/python tools/firmware/build_research.py
work/ncs-venv/bin/python tools/firmware/build_research.py \
  --target vimar-candidate --with-loader
work/ncs-venv/bin/python tools/firmware/build_research.py \
  --target vimar-candidate --stock-output --with-loader
```

These commands never access hardware. They use pristine builds because repeated
CMake reconfiguration in the pinned SDK can produce malformed security Kconfig
string exports. The script verifies signatures and records build commands,
image SHA-256 and artifact paths in `research-artifact.json` in each build directory.
The builder does not claim physical validation; consult the bench report for that.

The optional bundle includes the matching MCUboot, research main and BLE recovery.
Each HEX component is constrained to its assigned partition before merging; no
UICR or settings writes are included. The baseline Zigbee application built as a
sysbuild dependency is not included as the bundle's main application.

For the initial stock replacement the helper also prepares a distinct
`research-initial-install.hex`: it includes explicit0xff data for0xf0000..0xfffff
to initialize new settings/NVRAM partitions, where stock bootloader bytes may
otherwise remain. It still excludes UICR. This is an initial provisioning artifact,
not an OTA image or a storage-preserving update. Its use on the Vimar requires
the same device-specific review/approval as programming the other candidate images.
The BLE-only candidate is intended for the first connectivity/recovery checks;
the stock-output candidate can subsequently be uploaded over BLE for light tests.

The `vimar-candidate` overlay changes the local inputs to P0.26/P0.04, disables
unused DK peripherals and DK LED nodes, and uses the internal calibrated LF RC
clock rather than assuming the DK's 32.768 kHz crystal. It still inherits the DK
board definition and is a candidate port, not a hardware-qualified Vimar board.
It maps MCUboot's existing recovery button alias to UP. The eventual emergency
gesture is therefore **hold UP during power-up**; the normal runtime gesture is
**hold UP and DOWN for five seconds**. Both require validation on the actual unit
before remounting. The independent recovery image enables no power-stage outputs.

`CONFIG_RESEARCH_STOCK_CONFIG19` defaults to1 from the stock default configuration
record. The application does not yet read the unit's existing external EEPROM.
It does not reproduce stock min/max limits, ramps or auxiliary-input behavior.
P0.11/P0.20 physical roles and downstream fault feedback remain unresolved.

## Matching software recovery loader

Enabling `CONFIG_RESEARCH_SOFTWARE_RECOVERY` in the main app alone is insufficient.
MCUboot must also include `loader-software-recovery.conf`, which enables retained
boot-mode requests. The build helper's `--with-loader` option does this. The
original 2026-10-19 DK loader lacked that entrance method. A main-only update must
not advertise software recovery unless its installed loader actually supports it.

The new app calls `bootmode_set(BOOT_MODE_TYPE_BOOTLOADER)` and reboots. MCUboot
consumes/clears the retained request and boots the separately signed updater.
The app advertises as `Vimar30805-Lab`; updater name is `Vimar30805-Rescue`.
The updater handles application uploads; the main app exposes no self-overwrite
or arbitrary memory/register-write endpoint. The public development passkey is
824005, consistent with the existing DK environment; it is not a production key.

## Host console

With an existing authenticated BlueZ bond:

```sh
work/smpclient-venv/bin/python tools/firmware/research_console.py --address YOUR_BLE_ADDRESS status
work/smpclient-venv/bin/python tools/firmware/research_console.py --address YOUR_BLE_ADDRESS level 0
work/smpclient-venv/bin/python tools/firmware/research_console.py --address YOUR_BLE_ADDRESS off
work/smpclient-venv/bin/python tools/firmware/research_console.py --address YOUR_BLE_ADDRESS recovery
```

An explicit `--address` is required for the separately identified target. The client checks the custom service, response version, opcode and
sequence; device errors are not reported as success. It does not change host
adapter configuration or remove pairing records.

Command characteristic `fde30805-c001-4a40-8d00-308050000002` requires authenticated
read and write. Requests are exactly8 bytes: `<BBHi` = version1, opcode,
sequence uint16, argument int32 (little endian). Opcodes0/1/2 are status/level/
recovery. Non-level arguments must be0. Response is20 bytes `<BBHiiII` = version,
opcode, sequence, signed status, requested level, uptime milliseconds, flags.
Flags: bit0 simulated; bit1 software-recovery supported; bit2 stock-output
backend compiled; bit3 output fault latched. Sequence correlates a response;
it is not an anti-replay counter. BLE authentication protects the link.

## Verification and next physical steps

See the [historical evidence scope](../../docs/research-summary.md#architecture-and-current-status)
for actual DK and later Vimar results. The original optional Vimar image began
as build-verified only; that is not the status of all subsequent Vimar trials. Before programming the actual
Vimar: review the target/artifact and restore route, obtain device-specific
programming approval, then validate BLE reachability, both recovery entrances
and OTA on the accessible board. Only after those checks should the user remount
it and observe the light while the diagnostic commands are tested remotely.
Neither DK simulation nor signature checks establish Vimar power-stage behavior.

## Guided physical recovery-button checks

The installed corrected Vimar 0.4.1 revision can be checked interactively with
`work/smpclient-venv/bin/python tools/firmware/button_walkthrough.py --address YOUR_BLE_ADDRESS --main-hash EXPECTED_MAIN_SMP_HASH --recovery-hash EXPECTED_RECOVERY_SMP_HASH`. See
[`button_walkthrough.md`](../../tools/firmware/button_walkthrough.md). The tool
records operator confirmations separately from authenticated recovery/hash
observations and saves partial results on interruption. It does not observe
single-button events or program firmware. For historical physical OTA/restore
validation and current limits, see the [public evidence summary](../../docs/research-summary.md#architecture-and-current-status).

## Temporary alive/BLE LED (0.4.4 diagnostic image)

`CONFIG_RESEARCH_STATUS_LED=y` opts into PWM0 on candidate RGB pins P0.12/P0.06/P0.08.
Default builds leave this disabled. The temporary Vimar image0.4.4 keeps the
power-stage backend simulated, QSPI disabled and UICR untouched. Idle uses50%
duty on all three channels; authenticated BLE security levelL3 pulses between
25% and75% every half-second. Colors and physical polarity are not named:
intermediate duty remains nonzero under either polarity. It owns no PWM1/output
pins. DMA timeout disables PWM0 and releases the three GPIOs; it does not reset
the device. Recovery firmware is unchanged and has no such indicator.

The indicator represents this application's execution, not proof of SWD contact
or electrical power-off. GPIO/PWM register behavior is physically verified;
visible LED behavior requires operator observation. These are historical 0.4.4
results, not qualification of the current candidate. See the
[public interface summary](../../docs/research-summary.md#recovered-stock-interfaces).
