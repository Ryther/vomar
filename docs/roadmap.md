# Engineering roadmap

This page separates implemented architecture from remaining research. It is not
an installation checklist or a release qualification report. See
[architecture](architecture.md) for component ownership and
[research summary](research-summary.md) for dated evidence.

## Implemented source

The repository provides a pinned SDK/development graph, separate DK and Vimar
backends, configurable Zigbee dimmer behavior, an independent authenticated BLE
recovery application, signed compressed Zigbee OTA and typed loader contracts.
Android and desktop provide package validation, operation review, durable
sessions and first-install/repair machinery. The converter exposes schema-gated
configuration and diagnostics. Implementation does not establish physical
qualification of every route.

## Active engineering gaps

- Resolve APS-105-5241 with causal evidence for the exact source/binary. A smaller
  report or a no-assert interval does not demonstrate a fix.
- Qualify common first installation, inherited-watchdog start, generic stock
  restoration and update interruption on exact signed component sets.
- Establish native Android/Linux/macOS/Windows BLE/USB permission, driver,
  cancellation and restart behavior on real supported platforms.
- Measure electrical phase-cut behavior, load compatibility, auxiliary input
  routing and P0.31 protection/status semantics without overstating software
  output as a physical measurement.
- Close known compact desktop layout and accessibility gaps with actual renders
  and interaction evidence.

## Research scope

Retain stock secondary-controller firmware where practical. Continue only the
stock analysis needed for initialization, control, status, protection and safe
restoration. The recovered TWI transport is probable configuration EEPROM;
it does not establish a serial power-controller protocol. Compare Mesh/Zigbee
where that resolves a required interface.

Preserve immutable originals, hashes, reproducible scripts and evidence classes.
Read-only observation precedes any separately authorized physical change. See
[research rules](research-rules.md) and [goals](goals.md).

## Release gates

Release Please owns distribution versions/changelogs/tags. Exact-source software
checks, signer continuity, dependency/security review, physical qualification and
publication are separate gates. Explicitly accepted experimental firmware retains
its known issues and false qualification flags; publication does not close them.
See [releasing](releasing.md).
