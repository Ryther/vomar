# ADR 0002: Separate Zigbee DK and BLE recovery profiles

- Status: accepted for the DK prototype
- Date: 2026-08-24

This historical decision applies to the original equal-slot DK prototype.
The later [independent recovery decision](0003-independent-ble-recovery-dk.md)
and [current architecture](../architecture.md) describe its successor. The build
sizes and feasibility decisions below belong to the dated prototype.

## Context

The first nRF Connect SDK 3.4.0 build combining Nordic Zigbee R23, Bluetooth,
authenticated MCUmgr SMP, MCUboot, and two equal internal-flash image slots
overflowed the 466432-byte application partition by 46836 bytes. This is a
**CONFIRMED** build observation. Enlarging the primary image alone would remove
rollback; enlarging both slots is impossible within the nRF52840's 1 MiB flash
while retaining MCUboot, settings, and the required ZBOSS partitions.

The Zigbee-only DK profile builds at 377176 bytes (80.86% of its application
partition) and 57396 bytes of static RAM (21.89%). It therefore passes the
project gate requiring at least 15% free application flash and static RAM.

## Decision

Keep two explicit profiles during DK prototyping:

- the base profile remains the already validated BLE SMP recovery/FOTA image;
- `zigbee_dk.conf` disables Bluetooth and MCUmgr and exercises the Zigbee
  endpoint, state model, and DK simulation with the same internal-flash limits.

Both retain MCUboot, equal primary/secondary slots, ECDSA-P256 signing, and the
same fixed partition map. The Zigbee profile is programmed through the DK's
on-board debugger; it is not described as remotely updateable.

## Consequences

This separation lets Zigbee behavior be tested now without weakening the flash
budget or pretending BLE recovery coexists in the target image. It does not
solve application-independent recovery for the Vimar.

Before programming a Vimar, choose and validate a production recovery design.
Candidates include a smaller combined image, an application-independent
bootloader transport, or a deliberately different update layout. None is
accepted by this ADR.
