# SWD identity monitor and automatic state capture

Set your local J-Link serial and the two expected FICR DEVICEID words (hex, in
address order), then use the continuous monitor:

```sh
python tools/hardware/watch_vimar_swd.py --jlink-serial "$VIMAR_JLINK_SERIAL" \
  --uid "$VIMAR_DEVICEID0" "$VIMAR_DEVICEID1" --interval 1
```

To capture the next complete response from the exact Vimar, without coordinating
with the chat:

```sh
python tools/hardware/watch_vimar_swd.py --jlink-serial "$VIMAR_JLINK_SERIAL" \
  --uid "$VIMAR_DEVICEID0" "$VIMAR_DEVICEID1" --interval 1 --capture-state
```

Stop any other SWD monitor/debugger first. Leave the existing wiring and power
unchanged; a green result confirms the configured DEVICEID, not BLE readiness.

Capture mode rechecks DEVICEID in the same OpenOCD session, reads RESETREAS,
DHCSR, VTOR, fault registers, FPB and ACL control, and dumps the first16KiB of RAM
and all4KiB of UICR. It never requests halt, resume, reset, erase or programming.
The running RAM snapshot is not atomic. Memory and register reads over SWD are
not equivalent to a proof that debugger attachment has no hardware side effects.

Data goes under ignored `experiments/swd-contact-monitor/<timestamp>/`, with
raw OpenOCD log beside that folder. A `capture.json` marker and success message
are written only after OpenOCD succeeds and both dump sizes match. Partial
attempts are retained/retried and not reported as a completed capture. The
monitor then exits automatically, avoiding continued attach/detach cycles.

Treat raw RAM/UICR as private device evidence. No original input artifact is
modified. Ctrl+C stops the monitor; it does not reset the device.
