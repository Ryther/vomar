# Research summary

This page preserves the public engineering findings needed to understand and
reproduce the project. Raw dumps, proprietary decompilation, per-device identities
and detailed bench records remain local. **CONFIRMED** means directly supported
by code or an observed trial; **STRONG INFERENCE** and **HYPOTHESIS** retain their
uncertainty. A stock code trace proves what the nRF writes or reads, not the
physical endpoint or safety coverage of the downstream circuit.

## Architecture and current status

The custom application uses Nordic nRF Connect SDK/Zephyr with ZBOSS for Zigbee,
configurable gestures/timers, versioned persistent settings, LED policy and
manufacturer cluster `0xFC00`. The hardware backend and DK simulator are separate.
The hardware backend reports optimistic software output: it does not claim
power-stage acknowledgement or measured physical lamp feedback. See
[platform adapter](../firmware/src/platform_io_vimar.c) and
[Zigbee control contract](zigbee-controls.md).

The update architecture separates MAIN, authenticated BLE recovery and a protected
loader. Signed role/profile, slot geometry, component-pair and finite loader
contracts constrain updates. The compressed Zigbee OTA installer stages an
image outside its destination and authenticates it before reconstruction; BLE
provides the independent recovery route. The common Android package also carries
migration and stock-restoration helpers. Android 1.0.6 offers explicit original restoration from a device with its
retained matching original; its physical qualification is still pending. The
presence of restoration helpers alone does not qualify that path. See
[loader contracts](../firmware/loader_contract/README.md),
[common restore engine](../firmware/common_restore/README.md),
[Android workflow](android-updater.md) and [OTA contract](zigbee-ota.md).

**CONFIRMED, bounded evidence:** firmware 1.0.0's standalone-DK runtime trial
passed exact component/identity checks over authenticated BLE, controlled
MAIN error/abort recording, fault-record retention through recovery, ordinary
Bluetooth inactivity return, separately requested unclassified recovery remaining
active through the recorded 66-second window, and final byte-identical
FLASH/UICR/FICR restoration by SWD. The test used one existing PC bond. It did not
reproduce the originating Zigbee error, test a second phone bond, transfer a
Zigbee OTA image, cut power, exercise generic stock restoration, complete Android
first installation or validate the Vimar power stage. All thirteen signed physical
qualification flags remain false.

**CONFIRMED, historical evidence:** earlier exact DK images passed interrupted
transfers, wrong-key rejection, hung-application recovery and documented physical
power-interruption trials. Earlier Vimar images completed signed BLE updates,
full original-stock restoration/readback and later mounted-device updates with
preserved settings and network return. One owner-reported Android Bluetooth
update was corroborated by post-trial radio diagnostics, without a fresh full
image hash. These successes are real but apply to their recorded versions and
routes. They cannot promote 1.0.0 to fleet qualification or qualify the new
common-loader first-install and generic restore helpers.

## Recovered stock interfaces

| Interface | Confirmed nRF-side behavior | Remaining limit |
| --- | --- | --- |
| Local UP / DOWN | P0.26 / P0.04, active-low with pull-ups | Board assembly and behavior still need acceptance on each supported hardware scope. |
| Color LED | PWM0 on P0.12, P0.06, P0.08 | Physical color order and polarity were not established by the stock trace. |
| Dimmer output | PWM1 channel 3 on P0.13, 8 MHz clock, COUNTERTOP 1024; P0.14 high for valid level, low for OFF sentinel −32768 | Downstream electrical role and complete controller/protection contract remain unproven. |
| Configuration output | P0.19 follows a persistent configuration byte | Physical endpoint/meaning remains unresolved. |
| TWI | SCL P0.25, SDA P0.24, 400 kbit/s; 2 KiB logical range, addresses `0x50`–`0x57`, 16-byte write boundaries, CRC-16/CCITT-FALSE blocks | **STRONG INFERENCE:** 24C16-compatible configuration EEPROM. It is not evidence of a secondary-MCU command protocol. |
| Candidate protection/status input | No-pull P0.31 participates in output-inhibit/notification state in both stock images | Electrical endpoint, precise fault meaning and independent protection coverage remain unresolved. |

The P0.31 stock trace connects Mesh handler `0x49dd8` / level request `0x49594`
and Zigbee handler `0x3bc70` / request `0x3b9a8`: a qualified sustained LOW clears
inhibit; a qualified HIGH release following that LOW sets inhibit and requests
OFF. Inhibited level requests become OFF; clearing does not restore output by
itself. Startup constant-HIGH and outer dispatcher conditions are not fully
established. Do not label this an active-low fault input or a thermal-only
sensor. The custom implementation's conservative state and persistence behavior
is inspectable in [power protection](../firmware/src/vimar_power_protection.c);
normal LOW/no-trip observations do not establish physical fault coverage.

**STRONG INFERENCE:** the retained controller is an NXP/Freescale S08-family
part and manages the real-time power stage. PWM P0.13/P0.14 may form the control
interface. A framed serial protocol and the complete safety handshake have not
been established. See [hypotheses](hypotheses.md).

## Inherited stock watchdog

**CONFIRMED:** the examined stock applications start a watchdog with a nominal
ten-second period and pause-on-halt behavior. The actual target's live watchdog
configuration must still be checked before backup. The signed
`paused-reset-before-main-v1` capability permits only its bounded supported
profile: capture halts without feeding/resetting the watchdog, installation ends
halted, and a separate verified start hands control to a loader that waits for
one genuine watchdog reset before ordinary boot. Source implementation and
host checks do not establish a completed real-phone first-install trial. See
[Android installation](android-first-install.md) and
[handoff source](../firmware/common_restore_gate/inherited_watchdog_boot.c).

## Reproduce the static analysis

Obtain originals independently and retain them under ignored `inputs/`. The
repository does not redistribute the vendor APK, original Nordic DFU packages,
bootloader dumps or original application binaries. Expected application inputs:

| Target | Input | SHA-256 | Reset handler |
| --- | --- | --- | --- |
| Mesh | `inputs/firmware/mesh/P561_Dimmer_Mesh.bin` (213012 bytes) | `8c0408c49fe3e35758a69e511faa154c2f1237512e1c1bfdf1061221db53f927` | `0x00043F30` |
| Zigbee | `inputs/firmware/zigbee/P561_Dimmer_Zigbee.bin` (343988 bytes) | `710f788a02eca3985d5826efacf47cef8d8fa29dde4684815c25c8c9a79690d5` | `0x0002675C` |

Import as nRF52840 / Cortex-M4, little endian, Thumb at `0x00026000`. These are
application-only images. They do not include the stock SoftDevice or bootloader.
With Ghidra available, run from the repository root:

```sh
./tools/ghidra/run-analysis.sh mesh --dry-run
./tools/ghidra/run-analysis.sh mesh
./tools/ghidra/run-analysis.sh zigbee
```

The runner validates its input before import, creates disposable project state
under `work/ghidra/` and exports metadata, functions, strings/XREFs, fingerprints,
peripheral references and selected decompilation under ignored `analysis/`.
Originals remain immutable. Record source hashes and exact transformations for
new derived artifacts; retain `candidate_` / `probable_` names for tentative
semantics. See [research rules](research-rules.md).

**CONFIRMED:** the examined stock bootloader authenticates both recovered stock
DFU init packets with its embedded ECDSA P-256 public key and rejects unsigned
normal uploads. Installed-image `NO_VALIDATION` support is not an unsigned DFU
upload path. The public key cannot sign custom firmware; its private key has
not been recovered. Custom installation uses a separately approved SWD path and
the project's own signing trust root.
