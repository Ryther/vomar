# Zigbee2MQTT external converter

Converter **1.1.0** adds schema 8 phase-cut selection and standard Identify. Its
native version is independent of the distribution and firmware versions.

`dist/vimar_30805.js` is the standalone ESM external converter for the custom DK firmware identity
`Vimar30805-DK` and Vimar hardware identity `Vimar30805`. It registers cluster `0xFC00`, retains the standard dimmable-light
exposure, publishes gesture/system events as `action`, and provides individually
typed persistent settings plus volatile LED, timer-bypass, and snapshot commands.

Upload `dist/vimar_30805.js` through the Zigbee2MQTT frontend or the runtime
`bridge/request/converter/save` API. It contains no relative imports and does not
require a Zigbee2MQTT restart. The source remains split between `vimar_30805.js`
and `vimar_30805_core.js` for maintainability; regenerate the committed standalone
artifact with `npm run build`.

Zigbee2MQTT 2.13 and newer must have `advanced.enable_external_js: true` before
the runtime converter API is available. Changing that security gate requires a
Zigbee2MQTT restart; loading or updating the converter afterward does not.

Persistent settings are ordinary typed properties. For example, these MQTT writes
configure automatic switch-off and assign timed/bypass behavior to same-side clicks:

```text
auto_off_mode = every_on
auto_off_duration_s = 600
single_up_action = timed_on
double_up_action = bypass_on
```

Every setting supports state, set, and get and appears in the `config` category.
Diagnostics such as `timer_active`, `timer_remaining_s`, and `auto_off_bypassed`
are read-only. `led_override` is a typed composite, while `bypass_on`,
`clear_led_override`, and `request_snapshot` are set-only runtime triggers; none
requires user-facing JSON text.

The firmware validates the complete resulting configuration before accepting each
attribute, coalesces accepted writes for five seconds, and keeps timers and LED
overrides in RAM only. `stock_switch`, `acknowledged`, and `physical` remain
capability-gated by the firmware/secondary adapter.

Run the self-contained converter tests with:

```sh
npm test --prefix integrations/zigbee2mqtt
```

The tests also require the committed standalone artifact to match its two source
modules exactly.

The Vimar hardware profile also exposes `enter_recovery`: writing `true` requests
independent BLE recovery while preserving the current output. This command is not
implemented by the DK simulator. Hold both physical keys for five seconds as the
local fallback. The Zigbee main image does not advertise BLE during normal use.

The converter enables Zigbee2MQTT's standard OTA provider with `ota: true`, as
supported by the [current herdsman converter definition](https://github.com/Koenkk/zigbee-herdsman-converters/blob/master/src/lib/types.ts).
Actual updates require a custom main that implements the OTA client cluster
`0x0019` and a matching qualified recovery installer. Loading this converter does
not add OTA support to an older main, the stock Vimar firmware, or a simulator
that lacks that client. Hardware OTA qualification remains a separate gate.

`tools/firmware/package_zigbee_ota.py` prepares the signed compressed `.ota` image
and its private/local `index.json`. Configure that index as a
[custom OTA source](https://www.zigbee2mqtt.io/guide/usage/ota_updates.html#custom-ota-source)
in the Zigbee2MQTT environment; local artifact paths must resolve inside that
runtime. The package uses project test manufacturer `0xfff1`, image type
`0x3085`, hardware version `1` and a strictly newer MCUboot-derived file version.
The firmware authenticates and installs the compressed payload through recovery.
The ordinary primary-only BLE updater cannot install that compressed file.

For a previously registered stock device, re-interview and configure the custom
converter after initial custom installation. Retain its existing friendly name;
resolve the intended target by IEEE before requesting an update. Once a qualified
release is available from the private index, use the Zigbee2MQTT OTA update action
or the standard `bridge/request/device/ota_update/check` and
`bridge/request/device/ota_update/update` requests with that target's `id`.
Zigbee2MQTT publishes transfer progress through the device's `update` state.
Completed transfer alone does not prove successful recovery installation; verify
the new firmware version and preserved network, settings and physical output.

## Firmware 0.5.4 controls

The current converter is paired with firmware0.5.4 or later. Deploy the matching
firmware before activating the converter: ordinary output commands now use
custom command0x05 to honor local default delay/ramps; older applications do
not implement it. Explicit Zigbee transitions retain the standard light path.

The automatic LED profiles have two native color-light endpoints, `led_off`
and `led_on`, both mapped to physical endpoint1 and marked as HA configuration
entities. They write existing profile attributes only. The ON brightness slider
edits fixed intensity in `fixed`, and maximum intensity in `follow_level` or
`inverse_level`. Lowering the maximum below the minimum lowers the minimum first.
Profile edits never command the lamp or install a runtime override.

The original `led` endpoint and all35 persistent MQTT settings remain compatible.
The runtime light is now named "LED override manuale avanzato"; its HA discovery
is disabled by default only for new entities. Legacy RGB/intensity numbers also
use disabled-by-default discovery while remaining exposed in Zigbee2MQTT.
For existing devices, use the exact per-device discovery exclusions and runtime
entity registry migration documented in `../../docs/zigbee-controls.md`.
Do not remove the runtime entity if existing automations target it; hide it while
keeping it enabled. Existing saved settings always take precedence over defaults.

Verification: converter tests exercise native installed26.105.0 expose creation,
prepared definition validation, cached native HA metadata handling, profile-only
writes, mode-aware feedback and per-device partial reports. This is software
verification; live discovery and device readback are deployment checks.

Light brightness sliders now display0–100% in Zigbee2MQTT. Their feature
properties are `brightness_percent`, `brightness_percent_led_off`,
`brightness_percent_led_on` and the advanced `brightness_percent_led`.
They coexist with legacy raw `brightness` properties (0–254); supplying both
scales in one command is rejected. Home Assistant keeps native MQTT JSON
`brightness_scale:254` and the raw state keys, while displaying percentages
in its UI. Firmware settings and their raw min/max level contracts are unchanged.

Schema4 adds four reusable timer templates and ramp endpoint brightness controls;
see `docs/zigbee-controls.md` for actions and legacy MQTT compatibility.
Advanced lamp configuration brightness is exposed as percent aliases while raw
MQTT get/set remains supported. New controls are gated on the cached device
schema version; configure reads it before reading persistent settings.

After replacing a converter that adds custom attributes, run Z2M's **Configure**
action for each affected device (`bridge/request/device/configure`, with its
exact IEEE as `id`). Saving the converter updates its exposes but can leave the
device's in-memory custom-cluster table unchanged; re-interview alone does not
refresh that table. Confirm a fresh read of a newly added attribute afterward.
On an installed-dimmer trial, the stale table caused a named read to send an
empty ZCL payload and receive `MALFORMED_COMMAND`; the same numeric-ID read
worked, and Configure restored named reads and report decoding. This operation
does not require deleting or pairing the device again.

### Maintenance actions and recovery audit

Maintenance actions are configuration buttons (`press`), not persistent switches:
`clear_led_override`, `request_snapshot`, `bypass_on`, `enter_recovery`. Existing
MQTT boolean `true` still invokes the action; `false` does nothing. Other values
are rejected before sending a command. Physical Vimar reporting mode is a
read-only diagnostic (`optimistic`); the DK retains its configurable modes.

`extensions/vimar_recovery_audit.mjs` is an optional Z2M external extension. Its
current target list contains the three researched device IEEE addresses. It
observes requests containing `enter_recovery` on exact target `/set` or
`/set/enter_recovery` topics, and endpoint1 `vimarDimmer.enterRecovery` commands.
It sends no Zigbee commands. Records contain UTC time, IEEE, accepted/invalid
request value and command start/ack/error; arbitrary MQTT payloads are omitted.

Records go to INFO console and `/app/data/vimar-recovery-audit.jsonl` (0600),
rotating to `.1` after about 1 MiB. File failure falls back to console without
blocking commands. Removing the extension restores its endpoint wrappers.
Verify `ready` and its target count after restart or device replacement: targets
not present at extension startup are not dynamically added. The observer uses
Z2M's internal endpoint methods, so recheck compatibility after Z2M upgrades.

An acknowledgement does not prove a completed reboot. This trace cannot name an
HA automation, distinguish frontend WebSocket from broker MQTT, or observe local
button/boot-selector/OTA installer recovery entry. An absent entry alone does
not establish the cause. Device-side reset/recovery reason logging is planned
with the shared P0.31 protection work.

## Schema 8 phase selection and Identify

Use the matching converter and schema 8 firmware for `phase_cut_mode`:
`trailing_edge` (TE, default) or `leading_edge` (LE). The converter exposes the
setting only after reading schema 8. Switch the lamp OFF and wait for any delay
or ramp to finish before changing it. The setting is a guarded `setPhaseCut`
command (ID 6), followed by a matching `phaseCutMode` readback (attribute 0x0305).
The attribute itself is read-only; raw attribute writes cannot bypass admission.
A rejected command or mismatched readback is an error, not an optimistic success.
Send this setting separately from other settings.

Identify appears as a diagnostic press button in Home Assistant. MQTT
`{"identify":"identify"}` sends standard `genIdentify.identify` with
`identifytime: 15`: the LED flashes green rapidly while the lamp stays unchanged.
`press` and boolean `true` are accepted aliases; `false` does nothing. Faults have
priority. `led_runtime_effect=fast_blink` describes this temporary indication;
it is not a new manual LED effect. Configured profiles and manual overrides are
restored when Identify ends. A front long press while OFF now keeps the lamp OFF.

See the [firmware guide](../../firmware/README.md) for v5 settings migration,
downgrade limits and remaining physical qualification.
