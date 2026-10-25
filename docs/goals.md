# Project Goals

## Long-term goal

Develop a custom firmware for the Vimar 30805 nRF52840 while preserving the
original secondary power-controller firmware whenever practical and safe.

The goal is broader than fixing the current physical-button latency.

Desired behavior includes, eventually:

- short press on either side toggles ON/OFF;
- long UP increases brightness;
- long DOWN decreases brightness;
- release stops continuous dimming;
- configurable dimmable / switch-only / fixed-100%-output behavior;
- configurable minimum/maximum level and transitions;
- configurable power-on behavior;
- independently controllable button/status LED, including runtime/automation use;
- proper Zigbee state/control/reporting.

## First engineering milestone

Create a safe iteration loop:

1. initial programming through SWD;
2. subsequent application updates over BLE;
3. a recovery path that ideally does not depend on a healthy main application;
4. reliable restoration of a known-good development application.

## Reverse-engineering scope

Do not reconstruct the entire proprietary firmware.
Focus on interfaces and implementation details needed to safely replace the
nRF52840 side.
