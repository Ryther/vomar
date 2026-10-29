# Zigbee controls reference

The converter maps standard dimmable-light control and manufacturer cluster
`0xFC00` into Zigbee2MQTT properties. Read the target's `schema_version` and
capabilities before using a setting. Configure reads saved values; it does not
write defaults. Current wire ownership is `firmware/src/zigbee_custom_codec.h`,
`zigbee_custom_codec.c`, `zb_vimar_custom.h` and
`integrations/zigbee2mqtt/vimar_30805_core.js`.

Use [converter setup](../integrations/zigbee2mqtt/README.md) for installation and
reconfiguration. These are implemented controls, not physical qualification of
an arbitrary release. APS-105-5241 remains unresolved; see
[research evidence](research-summary.md).

## Defaults, ranges and units

These are new Vimar defaults from `dimmer_config_vimar_defaults()`. Updates retain
saved choices and default only newly introduced fields. The DK's generic defaults
differ: 250 ms long press, 100 ms step period, step 10, and different LED profiles.

| Property | Default | Range / meaning |
| --- | --- | --- |
| `double_click_window_ms` | 150 ms | 50–600 ms, same-side clicks |
| `long_press_ms` | 300 ms | 150–2000 ms |
| `level_step_period_ms` | 50 ms | 50–500 ms |
| `level_step_percent` | 1.2% (raw 3) | Raw 1–50; approximately 0.4–19.7% |
| `short_press_mode` | `symmetric_toggle` | `directional`, `symmetric_toggle`, `custom` |
| `single_up_action`, `single_down_action` | `toggle` | Used when short mode is `custom` |
| `double_up_action`, `double_down_action` | `event_only` | Independent action per side |
| `initial_on_delay_ms` | 0 ms | 0–60000 ms |
| `rise_transition_ms`, `fall_transition_ms` | 0 ms | 0–60000 ms each |
| `ramp_start_level_percent`, `ramp_end_level_percent` | 0% | Raw 0–254; schema 4+ |
| `timer_1_duration_s` … `timer_4_duration_s` | 600 s each | 1–86400 s; templates 2–4 require schema 4+ |
| `custom_power_on_behavior` | `local` | `local`, `await_zigbee` |
| `power_on_fallback` | `previous` | `off`, `on`, `previous` |
| `power_on_level_percent` | 100% | Raw 1–254 |
| `zigbee_restore_timeout_s` | 10 s | 1–300 s |
| `auto_off_mode` | `disabled` | `disabled`, `every_on`, `physical_on_only` |
| `auto_off_duration_s` | 600 s | 1–86400 s |
| `output_mode` | `dimmable` | Vimar supports `dimmable`, `fixed_level` |
| `reporting_mode` | `optimistic` | Read-only on Vimar; software estimate |
| `fixed_level_percent` | 100% | Raw 1–254 |
| `min_level_percent`, `max_level_percent` | 0.4%, 100% | Raw 1–254, min ≤ max |
| `phase_cut_mode` | `trailing_edge` | TE/LE, guarded command; schema 8+ |
| `led_on_red`, `led_on_green`, `led_on_blue` | 255, 254, 250 | 0–255 each |
| `led_off_red`, `led_off_green`, `led_off_blue` | 255, 110, 84 | 0–255 each |
| `led_on_intensity`, `led_off_intensity` | 10%, 25% | 0–100% |
| `led_on_mode` | `follow_level` | `fixed`, `follow_level`, `inverse_level` |
| `led_on_min_intensity`, `led_on_max_intensity` | 10%, 100% | 0–100%, min ≤ max |

Percent aliases round to the nearest raw level. Legacy `brightness` and
`brightness_led_*` remain 0–254; light controls expose `brightness_percent`,
`brightness_percent_led_off`, `brightness_percent_led_on` and
`brightness_percent_led`. Advanced numeric aliases append `_percent` to
`min_level`, `max_level`, `fixed_level`, `power_on_level`, `level_step`,
`ramp_start_level` and `ramp_end_level`. Raw names retain MQTT get/set.
Do not send raw and percent forms together. Home Assistant's MQTT JSON protocol
keeps `brightness_scale: 254` and raw state keys, while its UI shows percentages.
LED firmware intensity attributes independently use 0–100%.

## Gestures, timers and output

Either front short press toggles by default. `directional` maps UP to ON and DOWN
to OFF; `custom` uses the separate single actions. Same-side double clicks have
independent actions. `event_only` publishes the classified gesture without
changing the lamp; `disabled` suppresses that classified Zigbee event too.

Available actions include `toggle`, `on`, `off`, `timed_on`, `event_only`,
`disabled`, `bypass_on`, `timed_on_1` … `timed_on_4` and
`timed_toggle_1` … `timed_toggle_4`. Template actions require schema 4+.
`timed_on_N` always turns on/restarts timer N. `timed_toggle_N` starts it from
OFF, or turns off/cancels it from ON. Legacy `timed_on` (wire 3) and
`timer_duration_s` retain template-1 meaning; `timer_1_duration_s` is its alias.
New timer actions use wire 7–10 and 11–14; template 2–4 durations use UINT32
attributes `0x0207`–`0x0209`. OFF cancels the active timer. Timers remain volatile.

Front UP/DOWN long presses dim only an already applied ON output. Holding while
OFF, during an initial ON delay or unfinished OFF ramp leaves it OFF; release
does not become a short click. In fixed-level mode long gestures remain events
without local dimming. Wired auxiliary input has its separate one-button
behavior; see [firmware](../firmware/README.md#wired-auxiliary-push-button-candidate).

Normal converter light commands use custom `setOutput` (command 5) to apply local
default delay/ramps. Initial delay applies OFF→ON; rise applies increases; fall
applies decreases/OFF. Zero applies immediately. A newer request replaces an
active ramp; OFF cancels delayed ON. Explicit `transition` and standard direct
binding/scene commands retain the SDK transition path without another local ramp.
Local holds also avoid a second ramp. Startup/recovery are not delayed by defaults.

For nonzero ramps, `ramp_start_level_percent` selects the initial OFF→ON level,
bounded by target; zero starts OFF. `ramp_end_level_percent` selects the last ON
level before OFF, bounded by initial level; zero ends OFF. A ramp may pass below
`min_level`; the physical minimum is not calibrated. Fixed-level mode does not
use this ramp path. Min/max changes are ordered separate requests to keep a
valid interval. Interruption can leave a valid intermediate pair: reread it
before retrying. Fixed level is independent and min/max never prevent OFF.

Standard ON/OFF/brightness describe the accepted command immediately.
`applied_output_on`, `applied_output_level` and `transition_active` describe the
last software output command and local progress. They are not lamp measurements.
Application errors correct state and report faults. Acknowledged/physical
reporting and `stock_switch` require capabilities unavailable on the Vimar
adapter; simulator options do not establish hardware support.

## Automatic LED profiles

`led_off` and `led_on` are logical color-light configuration endpoints mapped to
physical endpoint 1. Editing them changes saved automatic profiles, never the
lamp or a temporary override. HS color becomes RGB profile attributes. MQTT
keys are `state_led_off`, `brightness_led_off`, `color_led_off` and `_led_on`
equivalents, plus their percent brightness aliases.

For `led_on_mode=fixed`, its slider edits `led_on_intensity`; `follow_level` and
`inverse_level` edit `led_on_max_intensity`. The minimum stays separate. Lowering
maximum below minimum writes minimum first. OFF in dynamic mode sets both to 0;
ON then restores maximum 10%, minimum 0 rather than the old range. Fixed/OFF
profiles set intensity 0 on OFF and restore 10% on ON if needed. An explicit
ON/TOGGLE-to-ON changes a legacy black RGB profile to white.

Follow mode computes `min + ((level-1)*(max-min)+126)/253` with integer division:
raw level 1 maps to minimum and 254 to maximum. Inverse mirrors that result.
Accepted software light level drives the calculation; fixed intensity remains
saved but unused in dynamic mode.

## Runtime LED override and discovery migration

The legacy `led` endpoint retains `state_led`, `brightness_led`, `color_led` and
`effect_led`. `effect_led=automatic` clears the override; `steady`/`slow_blink`
keep it indefinitely. Profile edits do not remove an active override. Priority
is fault, override, temporary indication, automatic profile; Identify is a
temporary indication with its own standard command.

For a fifteen-second amber override, publish to
`zigbee2mqtt/YOUR_DEVICE/set`:

```json
{"led_override":{"red":255,"green":160,"blue":0,"intensity":25,"effect":"steady","duration_ms":15000}}
```

This runtime command changes no saved profile or lamp output. `duration_ms:0`
lasts until clear/reboot; `{"clear_led_override":true}` clears immediately.
Maintenance actions `clear_led_override`, `request_snapshot`, `bypass_on` and
`enter_recovery` are press actions; legacy boolean true invokes them, false does
nothing. Other values are rejected.

New Home Assistant discovery disables legacy RGB/intensity numbers and runtime
light by default. Existing entity registry choices are retained. To remove
legacy discovery, configure only the intended device:

```yaml
homeassistant:
  led_on_red: null
  led_on_green: null
  led_on_blue: null
  led_on_intensity: null
  led_off_red: null
  led_off_green: null
  led_off_blue: null
  led_off_intensity: null
  # Only if existing automations no longer use the runtime light:
  light_led: null
  effect_led: null
```

These object IDs have no `number_` prefix. Migrate automations before removing
entities. To retain runtime automations while showing only two profile lights,
hide the advanced runtime entity in Home Assistant while keeping it enabled.
The converter cannot override an existing entity registry choice.

## Recovery, persistence and schema compatibility

Settings record v5 reads v1–v4 and appends phase selection. Older firmware cannot
decode v5, so downgrade is not a preserving migration. Before BLE recovery,
configuration and remembered brightness are saved immediately, including inside
the coalescing window; save failure cancels reboot. Warm handoff retains exact
applied ON output or remembered OFF brightness. An interrupted ramp does not
restart automatically. Physical continuity needs observation.

Schema gates distinguish the wire contract from settings-record versions:
schema 4 adds timer templates/ramp endpoints; 5 adds P0.31/boot diagnostics;
6 adds read-only `ota_contract`; 7 adds build-bound fault diagnostics; 8 adds
phase selection. Older supported schemas read only known attributes and hide
unavailable controls. Configure reads schema before settings and refreshes the
custom-cluster metadata after converter replacement.

## Schema 8: phase-cut mode and Identify

Send `phase_cut_mode` separately with `trailing_edge` (TE) or `leading_edge` (LE),
only when accepted, target and applied lamp output are all OFF and delays/ramps
have finished. Guarded command 6 persists before applying P0.19 and verifies
read-only `phaseCutMode` attribute `0x0305`. Raw attribute writes cannot bypass
admission. Failed persistence leaves mode unchanged; unexpected apply failure
inhibits output and reports a fault. Electrical mode/load compatibility remains
physically unqualified. Older settings default to TE unless explicitly built
with the reviewed override; see [firmware](../firmware/README.md).

Identify uses standard `genIdentify.identify` for 15 seconds. Publish
`{"identify":"identify"}` (`press`/true aliases accepted; false does nothing).
The LED flashes green at 5 Hz without changing lamp or saved configuration.
Fault indication takes priority. The previous profile or unexpired override
returns afterward. IdentifyTime=0 cancels it. `led_runtime_effect=fast_blink` is
a diagnostic, not a newly accepted manual override effect.

## Versions and verification

Basic `SWBuildID` (`0x4000`) comes from Zephyr `APP_VERSION_STRING`/`VERSION` and
is limited to sixteen characters. OTA `installed_version`/`latest_version` are
separate encoded numeric versions. Transfer progress can retain cached catalogue
versions, especially with direct file upload; correlate the final from/to
response, authenticated postboot identity/hash, network/settings and physical
checks. Never rewrite device attributes merely to correct server-side cache.

Run `npm test --prefix integrations/zigbee2mqtt` and affected firmware host suites
for source changes. Historical test counts, package margins and mounted-device
trials apply only to their exact recorded images. Current fit, Home Assistant
discovery, device readback, visible ramps and physical interruption each require
their own evidence; no generic test-count paragraph qualifies them.

Historical fit evidence: the 0.5.6 candidate used 253729 of 253952 package bytes
(223 bytes free), with 44 converter tests and 237 Python/18 C host tests reported
for that snapshot. Earlier 0.5.4/0.5.5 trials observed OTA/boot/readback on three
dimmers. Those dated observations neither describe current package margin nor
qualify current ramps, Home Assistant discovery or physical power-cut recovery.
