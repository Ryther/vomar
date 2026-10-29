# Project goals

Vomar replaces the Vimar 30805 nRF52840 firmware while retaining the original
secondary power-controller firmware wherever practical and safe. The scope is
broader than the original physical-button latency problem.

## Product behavior

Provide autonomous local ON/OFF and dimming, configurable gestures/timers,
brightness limits/transitions, power-on policy, independent LED profiles and
runtime overrides, plus standard Zigbee control/reporting and diagnostics.
The source implements these components; the
[control reference](zigbee-controls.md) defines their supported current behavior.
A software feature is not a claim of measured lamp output or complete electrical
protection. A physical bypass or stock switch mode remains unproven.

## Safe iteration and recovery

Maintain an explicit, device-bound initial installation with two equal original
captures, verified archive save/reopen and bounded writes. Preserve original
material and interrupted-session evidence; installation completion ends halted
before a separately reviewed start. Subsequent BLE/Zigbee updates must retain
signer continuity, exact live identity, role/pair/loader contracts and an
independent recovery route. Full stock restoration has a distinct trust and
power-loss boundary.

The architecture is implemented, while first-install, generic restoration,
platform transport and physical firmware qualification still require their own
exact-artifact evidence. Resolve APS-105-5241 before claiming that failure fixed.
See [roadmap](roadmap.md) and [research summary](research-summary.md).

## Reverse-engineering boundary

Reconstruct only interfaces needed to initialize, control, monitor and safely
restore the nRF side. Preserve immutable vendor evidence and distinguish
confirmed nRF operations from inferred physical endpoints. Do not broaden into
unrelated proprietary behavior. Read-only analysis precedes any explicitly
authorized physical programming or measurement.
