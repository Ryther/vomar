# ADR 0003: Independent BLE recovery for the DK prototype

- Status: accepted DK prototype; basic OTA and recovery fault scenarios bench-validated
- Date: 2026-10-19

This ADR records the original DK prototype decision. Later hardware/common-package
behavior and qualification limits are summarized in the
[current research summary](../research-summary.md).

## Decision

Add an opt-in `ota` profile using the pinned SDK's MCUboot firmware-loader mode:
a 656 KiB Zigbee application slot and a 256 KiB signed BLE recovery image, with
48 KiB for MCUboot. Preserve the settings/ZBOSS regions and the ADR 0002 profiles.
Do not assume an external flash chip exists on the Vimar.

MCUboot checks signatures on every boot. Its boot-time DK button trigger does
not require the application, and an invalid primary image selects the recovery
image. BLE SMP requires authentication; only the application is uploaded.

## Tradeoffs and limits

- One application slot means no automatic rollback to the previous version.
- Interrupted updates can require uploading again through recovery.
- Zigbee is stopped while the BLE updater runs.
- A validly signed but crashing application requires a reset and recovery trigger;
  signature validation cannot detect application logic failures.
- The updater is separate from ordinary application uploads, but is not yet
  protected against arbitrary flash writes by a defective application.
- Bootloader/updater OTA updates, production credentials, remote recovery entry,
  the Vimar trigger and measured fault recovery are outside this software result.

This architecture removes the combined-radio application-slot limitation and
provides a testable independent recovery route. It does not establish physical
Vimar compatibility or permission to program an attached target.

DK acceptance results are recorded in
the [public evidence summary](../research-summary.md#architecture-and-current-status). Interrupted transfers followed
by reset, wrong-key fallback, recovery from a deliberate application hang and
power-cycle pairing passed. A subsequent manual USB power-cut during upload also
returned automatically to recovery. The precise flash-programming instant of
that cut was not measured.
