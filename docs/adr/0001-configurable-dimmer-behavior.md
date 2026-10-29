# ADR 0001: Configurable local and Zigbee dimmer behavior

- Status: historical design record; implemented behavior is owned by current source
- Date opened: 2026-08-19
- Scope: desired behavior of the custom Vimar 30805 nRF52840 firmware

## Context

The custom firmware must behave as a dependable wall dimmer without a coordinator,
while also exposing richer gestures, configuration, state, and diagnostics through
Zigbee. It must preserve the stock secondary power-controller firmware where safe
and practical. Unconfirmed proprietary interfaces remain gated on static analysis
and hardware measurements.

This record preserves the original design intent, including plans that later
changed. It is not a current wire contract or physical qualification report.
Use [Zigbee controls](../zigbee-controls.md), `firmware/src/dimmer_config.c`,
`application_controller.c`, `zigbee_custom_codec.h` and `platform_io_vimar.c`
for implemented behavior. The TWI interface below was later identified as a
probable configuration EEPROM, not a proven power-controller command bus; see
[research summary](../research-summary.md#recovered-stock-interfaces).

## Overall approach

Use a structured configurable firmware, not a minimal Zigbee-only device and not a
general-purpose local rules engine. Local behavior is autonomous and predictable;
Home Assistant can use event-only gestures for arbitrary automations.

The design is divided into independently testable components:

- `button_input`: physical edges and timestamps;
- `gesture_classifier`: single, double, long, and release recognition;
- `local_action_mapper`: configured gesture-to-action mapping;
- `light_controller`: logical state, target level, transitions, and output mode;
- `secondary_mcu`: the only interface to the stock power controller;
- `local_timer`: volatile countdown behavior;
- `led_controller`: normal profiles, volatile overrides, and critical indications;
- `zigbee_device`: standard control plus configuration, events, and diagnostics;
- `settings_store`: compact, versioned, validated persistent settings;
- `fault_manager`: bus, reset, and requested-versus-confirmed state faults.

No general-purpose rule engine is planned.

## Button gestures and events

- The default short-press profile is `symmetric_toggle`: either side toggles the
  light.
- `directional` preserves the stock-style behavior: UP turns on and DOWN turns off.
- `custom` permits independent UP and DOWN mappings.
- Common mappings are the default; an advanced mode permits per-side mappings.
- A double click consists only of two presses on the same side. Mixed UP/DOWN
  sequences are separate single gestures.
- Raw `press_up` or `press_down` is emitted immediately.
- Final `single_up`, `single_down`, `double_up`, or `double_down` classification is
  emitted after the double-click window.
- A long press emits one `long_up` or `long_down`, followed by `release_up` or
  `release_down`. No periodic `hold` traffic is emitted.
- Release events include the measured `held_ms`, final light level, and a sequence
  identifier suitable for duplicate detection.
- Double-click and long-press thresholds are configurable within safe bounds and
  have usable defaults. Initial candidate defaults are 250 ms and 500 ms,
  respectively; hardware usability testing will set final defaults.
- UP always increases and DOWN always decreases during local dimming. Direction
  inversion is intentionally excluded.

Allowed local actions for single and double gestures are:

- `toggle`;
- `on`;
- `off`;
- `timed_on`;
- `event_only`;
- `disabled`.

Double-click recognition and the local timer are independent. A double click may
be event-only for Home Assistant. In non-adjustable output modes, long presses may
still emit `long` and `release` events but do not change the local output level.

## Local timer

- The timer is associated with a configured gesture; it is not intrinsically tied
  to double click.
- `timed_on` turns on a light that is off, starts a timer for a light already on,
  and restarts an already active timer from its configured duration.
- Any OFF command, whether local or Zigbee, cancels the timer.
- Brightness changes and ordinary ON commands do not cancel it.
- Expiry turns the light off locally and reports the event and state.
- Runtime timer state is RAM-only. It is forgotten after any reset or power loss,
  avoiding flash writes per timer activation.
- After restart, the general power-on policy applies; the expired volatile timer is
  not reconstructed.

## Power-on policy

Power restoration is represented by separate settings:

- `power_on_behavior`: `local` or `await_zigbee`;
- `power_on_fallback`: `off`, `on`, or `previous`;
- `power_on_level`: level used when the result is ON;
- `zigbee_restore_timeout`: maximum coordinator wait.

`local` applies the configured fallback immediately. `await_zigbee` initially keeps
the output off, announces a restore request, accepts a desired state from the Zigbee
side, and applies the configured fallback on timeout. A physical button action has
priority and cancels the wait. The device remains locally usable without a working
coordinator.

## Output modes

The planned conceptual modes are:

- `dimmable`: ON/OFF and continuous local level adjustment;
- `stock_switch_mode`: reproduce Vimar's non-dimmable semantics only after the
  secondary-MCU behavior is established;
- `fixed_level`: ON always uses a configured fixed level and long presses are
  event-only locally.

Do not call any mode `bypass` without electrical evidence for a distinct physical
bypass path.

Current stock evidence:

- **CONFIRMED:** the APK maps proprietary `DEVICE_BEHAVIOUR_PID` bytes
  `{0x01, 0x0c}` to value `1` for `Dimmerable_ON` and `0` for
  `Dimmerable_OFF`.
- **CONFIRMED:** selecting non-dimmable disables minimum level, soft start, soft
  stop, and dimming speed in the app, while enabling timed-switch settings.
- **CONFIRMED:** the Mesh image contains a distinct `DIMMER_BEHAV` property whose
  observed default is `1`.
- **STRONG INFERENCE:** non-dimmable is a logical switch mode. Whether it commands
  100 percent conduction or a dedicated secondary-controller mode is unresolved.
- **HYPOTHESIS:** a physical power-stage bypass exists. There is currently no
  supporting electrical evidence.

The first-version validation compares stock `dimmable = 100%` against
`non-dimmable = ON` on the internal bus. Matching commands support a 100-percent
translation; a distinct opcode, flag, or configuration supports a dedicated mode.
This protocol result is sufficient for initial implementation. Actual physical
bypass verification is deferred until correctly isolated mains-rated measurement
equipment and an approved procedure are available.

## Zigbee state reporting

Gesture events are independent of light-state reporting and retain the timing
defined above. State reporting is configurable:

- `optimistic` (default): publish accepted target state immediately, then correct
  it and publish a fault if the operation fails;
- `acknowledged`: wait for a reliable secondary-controller command acceptance but
  not for transition completion;
- `physical`: wait for confirmed or estimated physical completion.

`target_state` and `target_level` may always be reported immediately. Modes that
depend on an internal acknowledgement are exposed only if hardware/protocol
validation proves the necessary signal. If physical confirmation is unavailable,
the corresponding status is explicitly identified as estimated.

The device speaks Zigbee; Zigbee2MQTT is responsible for translating its events and
attributes to MQTT.

### Zigbee representation

Endpoint 1 remains a standard Home Automation dimmable light. Effective light state
uses the standard On/Off and Level Control server clusters so ordinary Zigbee
controllers can operate the device without understanding its advanced features.

A single manufacturer-specific server cluster at `0xFC00` carries configuration,
gesture events, volatile LED control, pending target, and diagnostics. It uses
fixed-width attributes and compact commands rather than multiple endpoints or
encoded JSON. The cluster exposes a schema version and capability bitmap. A
Zigbee2MQTT external converter maps its settings and events to named MQTT/Home
Assistant properties. The complete attribute ranges, commands, validation rules,
and initial limits are specified in
[the public Zigbee control contract](../zigbee-controls.md).

### State authority and reconciliation

The effective physical state is always authoritative. Zigbee2MQTT and Home
Assistant may temporarily hold a stale cached state after a timeout or lost
report, but that cached value must never be interpreted as a new command or used
to overwrite the physical state implicitly.

An explicit, newly received Zigbee command may change the target state. After the
command, the reporting mode above determines when the target or confirmed state is
published. If execution fails or later physical feedback disagrees with the
target, the device reports the effective physical state and the coordinator must
converge to it.

Reconciliation uses standard Zigbee mechanisms plus bounded application policy:

- report `OnOff` and `CurrentLevel` whenever their effective values change;
- request end-to-end delivery acknowledgement for unicast reports and use bounded
  retry with backoff after delivery failure;
- publish a complete state snapshot after join, rejoin, network restoration, and
  application restart once the effective state is known;
- periodically republish a complete state snapshot as a heartbeat so one lost
  change report cannot leave the coordinator stale indefinitely;
- keep the effective attributes readable so Zigbee2MQTT can reconcile with a ZCL
  Read Attributes request, including its availability state-retrieval flow;
- expose a pending target or fault separately; never encode an unconfirmed target
  as confirmed physical state.

Initial reconciliation parameters are:

- a complete periodic snapshot every 60 seconds;
- at most three application retries after a failed report;
- candidate retry delays of 1, 3, and 10 seconds.

DK network tests may justify revising these values. Reconciliation itself is
runtime behavior and must not cause flash writes.

## LED behavior

Persistent normal profiles are implemented locally and remain functional without a
coordinator:

- independent RGB color and intensity for light ON;
- independent RGB color and intensity for light OFF/standby;
- zero intensity disables the LED in that state;
- normal persistent profiles use a static effect.

When the light is ON, intensity mode is configurable as:

- `fixed`;
- `follow_light_level`;
- `inverse_light_level`.

Following modes map light level into configured LED minimum and maximum intensity.
Runtime level updates do not write flash.

A Zigbee LED override is volatile and held only in RAM. It includes RGB color,
intensity, optional effect, and optional duration. It ends on expiry, explicit clear,
or reboot. It survives ordinary light-state changes. Priority is:

1. critical fault and recovery indication;
2. volatile Zigbee override;
3. temporary gesture or timer indication;
4. persistent ON/OFF profile.

When a higher-priority temporary indication ends, the still-active lower-priority
state resumes.

## Persistence and resource policy

- Persist only validated configuration and deliberately selected long-lived state.
- Keep gesture state, timers, LED overrides, transitions, and transient reports in
  RAM.
- Do not save on every dimming step or timer tick.
- Coalesce settings updates and avoid writing unchanged values.
- Use versioned settings, integrity validation, and a migration/default path.
- Measure flash and RAM budgets at every firmware milestone.

## Deferred useful capabilities

The architecture should permit, but the first implementation need not include:

- night profile or reduced maximum level;
- general auto-off independent of gesture timer;
- child lock while retaining configured events;
- operating-time and switching counters;
- reset, fault, and secondary-link diagnostics;
- Zigbee identify indication;
- configuration export/import;
- thermal or overload reporting only if the secondary controller supplies reliable
  data.

## Hardware validation gates

Before implementing proprietary power control:

1. Map P0.24/P0.25 unpowered from the nRF52840 to connector and peer endpoints.
2. Establish logic ground, voltage, and isolation before attaching USB instruments.
3. Capture probable I2C at boot and during controlled stock operations.
4. Compare dimmable levels with stock non-dimmable ON as described above.
5. Record original captures, hashes, wiring, sample rate, firmware version, and
   exact stimulus.
6. Keep physical mains-waveform/bypass characterization as a separate gated test.

No logic analyzer whose ground is tied to a computer may be attached to an
unverified mains-referenced domain.

## Open design questions

- Final usability-tuned configuration defaults within the safe ranges established
  by the complete-firmware design.
- Exact secondary-MCU initialization, framing, command, acknowledgement, state, and
  fault semantics.
