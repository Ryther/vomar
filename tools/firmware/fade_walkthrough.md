# Compare dimmer fade-in behavior

Use this guide only after explicit approval to operate the exact lamp on an
authorized Zigbee2MQTT deployment. It changes lamp state/brightness; it does not
update firmware or write configuration parameters. Normal firmware may persist
the resulting state. Automated tests must use disposable services and fixtures.

Set the target IEEE and exact WebSocket API URL, then run in the prepared Python
environment:

```sh
python tools/firmware/fade_walkthrough.py --ieee "$VIMAR_ZIGBEE_IEEE" --url "$VIMAR_Z2M_WS_URL"
```

There is no default target/server. Add `--origin` for a proxy if needed. Private
credentials default to `work/private/z2m-cookie.txt`; select another local file
with `--cookie`. Never put cookie bytes into chat or public reports. Preview
without network, credentials or lamp commands:

```sh
python tools/firmware/fade_walkthrough.py --dry-run
```

## Compare the two ramps

The tool first checks identity, reachability and settings. An unreachable target
or active timer/transition/auto-off blocks preparation without configuration
changes. Each Enter authorizes only the single action described in the terminal.

1. Run the first ON test from OFF and record the observed jump/delay.
2. In the second test, confirm the lamp is stable at minimum. A further Enter
   starts the rise to the same target. Time at minimum includes your observation
   and response; it is not bounded to half a second.
3. Optionally restore the initial state/level with separate command confirmations.
   Restoring remembered brightness when initially OFF may first require ON at
   that level, then OFF; the terminal describes both actions.

The default target is remembered brightness, or 32.3% if it was at minimum,
limited by configured maximum. Set a target explicitly when needed:

```sh
python tools/firmware/fade_walkthrough.py --ieee "$VIMAR_ZIGBEE_IEEE" --url "$VIMAR_Z2M_WS_URL" --target-percent 35
```

`q`, `stop` or Ctrl+C prevents further commands and **does not restore** initial
state automatically. The lamp stays at the reached state. Do not change settings
or use other controls during comparison. Software output feedback is an estimate,
not an optical measurement. Results are saved immediately under a new ignored
`experiments/fade-walkthrough/` directory, shown in the terminal; `--output`
selects another new directory. Reports omit the cookie.

## Compare short pauses at minimum

```sh
python tools/firmware/fade_walkthrough.py --ieee "$VIMAR_ZIGBEE_IEEE" --url "$VIMAR_Z2M_WS_URL" --startup-holds-ms 100,300,1000 --target-percent 32.3
```

This mode requires schema 5, enabled/valid/unblocked P0.31 monitoring, initial
ON delay 0 and a nonzero rise ramp. It uses normal lamp OFF, with no power cut or
configuration change. It runs the OFF→target reference, then for each pause asks
Enter to turn OFF immediately and wait three seconds. Another Enter authorizes
direct ON at minimum, software confirmation, the additional pause and the same
rise. Record the result afterward. Ctrl+C stops subsequent commands during the
sequence; `q` works at input prompts.

100/300/1000 ms are waits **after software confirmation**, not exact physical dwell
times. Zigbee delivery/response latency adds to them. Logs record minimum-confirm
latency, observed PC wait and request interval, not light-waveform timing or
power-stage acknowledgement. Do not use these timings as electrical calibration.
