# Vimar 30805 Reverse Engineering Workspace

This repository is a local research workspace for reverse engineering the
Vimar View Wireless Linea 30805 dimmer and preparing a custom nRF52840 firmware.

Before substantial work, read:

- `docs/goals.md`
- `docs/known-facts.md`
- `docs/hypotheses.md`
- `docs/research-rules.md`
- `docs/firmware-layout.md`
- `docs/roadmap.md`

## Repository roles

- `inputs/`: original source artifacts. Treat as immutable evidence.
- `third_party/openvsh/`: upstream OpenVSH checkout. Reference-only unless explicitly requested.
- `analysis/`: research notes, validated findings, and generated RE output.
- `tools/`: reproducible analysis helpers and Ghidra scripts.
- `work/`: mutable Ghidra projects/tool state.
- `experiments/`: disposable derived artifacts; never overwrite `inputs/`.

## Evidence discipline

Every semantic conclusion about proprietary firmware must be classified as one of:

- **CONFIRMED**: directly supported by code, strings, XREFs, hardware observation,
  protocol capture, or another reproducible artifact.
- **STRONG INFERENCE**: multiple observations support it, but it is not directly proven.
- **HYPOTHESIS**: plausible and still requires validation.

Never silently promote an inference or hypothesis to confirmed fact.
Use `candidate_*` or `probable_*` names for tentative semantic function names.

## Safety

Analysis is read-only by default.

Never autonomously execute destructive commands against physical hardware.
In particular, never execute or recommend executing without explicit approval:

- `nrfjprog --recover`
- `nrfjprog --eraseall`
- `nrfjprog --chiperase`
- mass erase
- UICR writes
- bootloader writes
- programming a physical device

Never modify original `.bin`, `.dat`, APK, or dump files under `inputs/`.
Derived binaries must be written under `experiments/` or `analysis/` and must
record the source SHA-256 and exact transformation.

## Current preferred architecture

The current direction is to investigate whether we can:

1. replace the nRF52840 firmware with our own firmware;
2. preserve the stock secondary MCU / power-stage firmware;
3. reverse engineer only the interfaces necessary to operate the hardware safely;
4. establish a robust BLE firmware-update/recovery path early;
5. then implement button behavior, LED behavior, secondary-MCU communication,
   and Zigbee.

This is a preferred direction, not yet a proven architecture.

## Primary targets

Prioritize:

1. OpenVSH architecture and BLE FOTA/recovery implementation;
2. physical button GPIO/event handling;
3. button/status LED control;
4. nRF52840 <-> secondary MCU physical and logical interface;
5. secondary-MCU commands and status/fault behavior;
6. equivalence mapping between Mesh and Zigbee stock firmware.

Avoid reverse engineering unrelated application behavior unless it helps one
of these targets.

## Ghidra import facts

Target:

- Nordic nRF52840
- ARM Cortex-M4
- little endian
- Thumb

Raw application image base:

- `0x00026000`

Mesh:

- expected file: `P561_Dimmer_Mesh.bin`
- reset handler: `0x00043F30`

Zigbee:

- expected file: `P561_Dimmer_Zigbee.bin`
- reset handler: `0x0002675C`

Prefer reproducible Ghidra headless/scripts over repeated manual GUI work.
Use the GUI to validate important findings and inspect Function Graphs.
