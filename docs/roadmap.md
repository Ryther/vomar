# Research Roadmap

## Phase 1 - Workspace and source inventory

- preserve current Mesh/Zigbee/APK/JADX artifacts;
- clone OpenVSH;
- hash original inputs;
- make the toolchain reproducible inside the Dev Container.

## Phase 2 - OpenVSH reconnaissance

Determine with exact source references:

- nRF Connect SDK / Zephyr architecture;
- bootloader/FOTA mechanism;
- partition layout and signing;
- recovery behavior;
- physical button handling;
- LED handling;
- Zigbee endpoint architecture;
- reusable Vimar abstractions.

## Phase 3 - Automated stock-firmware analysis

Create Ghidra headless/scripted analyses for Mesh and Zigbee and export:

- function inventories;
- strings and string XREFs;
- selected decompilation;
- call graphs;
- Mesh/Zigbee similarity candidates.

## Phase 4 - Hardware-interface discovery

Determine:

- physical button GPIOs;
- LED control;
- nRF <-> secondary-MCU physical interface;
- initialization/handshake;
- command framing;
- state/fault reporting.

## Phase 5 - BLE development/recovery platform

Establish on a safe development target first:

- known-good boot/recovery design;
- BLE firmware transfer;
- image validation/signing;
- recovery from a broken application.

## Phase 6 - Minimal custom application

Progressively implement boot/logging, buttons, LED, secondary-MCU status,
ON/OFF, level control, and continuous dimming.

## Phase 7 - Zigbee

Add On/Off, Level Control, reporting, configuration, and Home Assistant /
Zigbee2MQTT behavior.
