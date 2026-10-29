# Legacy Zigbee-to-Bluetooth migration reference

This page explains a historical compatibility bridge, not a general recipe for
all old dimmers. Use [Android Bluetooth trial](android-bluetooth-trial.md) or
[desktop](desktop.md) for current supported actions. A device already running a
compatible independent recovery does not need an arbitrary intermediate update.

## Supported transition and purpose

The recorded 0.6.3 intermediate targeted the finite MAIN 0.5.5 / RECOVERY 0.7.1
source set through its existing Zigbee OTA path and installed RECOVERY 0.8.3.
That recovery retained up to eight Bluetooth associations, allowing an existing
PC association and phone association to coexist; one connection was active at
a time and the bridge did not evict a bond. These are properties of that exact
historical set, not version-only permission to use any similarly named file.

Current migration admission must verify the signed package, finite loader/source
policy, exact live target, OFF state, image roles and embedded recovery binding.
An unsupported source, missing original or mismatching identity blocks the
operation. Do not substitute a package from an old experiment directory or pick
the newest filename as authority. Preserve private original stock backups.

## Operator boundary

Migration changes installed firmware. Obtain explicit review for the exact
target, signed artifacts and expected recovery transition. Keep power available
through download/recovery replacement and close other Bluetooth clients.
Recovery remaining active after the intermediate can be intentional; final MAIN
installation is a separately reviewed operation. Pairing or discovering it does
not grant update authority. Do not perform a breaker/power cycle merely because
an earlier trial did so; use the current target-specific reviewed procedure.

After a final update, independently verify image identity where available,
Zigbee network return, settings, buttons and lamp. On interruption, retain
reports/journals and inspect durable state before a fresh action. Do not
recapture mixed firmware as an original or discard a PC bond to free a slot.

## Evidence limits

Historical native/signature/decoder/host checks supported a controlled trial.
One owner-reported phone update was corroborated by post-trial radio diagnostics,
without a fresh authenticated complete-image hash. Additional-phone enrollment,
output continuity and exact-route power-cut qualification were separate gaps.
The fatal-reset routing correction did not resolve APS-105-5241. Published
acceptance or a completed trial does not convert false qualification flags into
physical proof. See [research summary](research-summary.md).
