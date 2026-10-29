# Measure an observed BLE startup interval

This bench tool measures one manually controlled power cycle of the historical
BLE research application. Obtain explicit approval for the exact target and
manual power actions. Keep approved isolated bench wiring and power; stop SWD
monitors/other BLE clients and leave Vimar buttons released. Do not connect a DK
to a mains-powered dimmer.

In the prepared BLE Python environment, select the exact target address:

```sh
python tools/firmware/measure_boot.py --address "$VIMAR_BLE_ADDRESS"
```

For instructions without BLE access, add `--plan`. The address distinguishes
the intended Vimar from the DK; a radio name is insufficient.

## Follow the measurement sequence

1. Wait for the authenticated current MAIN response before switching off. Failure
   here blocks the measurement.
2. Press Enter; at **ORA SPEGNI** (“switch off now”), remove approved bench power
   and confirm with Enter.
3. Leave power disconnected for at least 120 seconds. The tool reports elapsed,
   remaining and advertisement-silence times every five seconds. It additionally
   requires ten consecutive seconds with no target advertisements; each callback
   restarts that counter. Radio silence is not electrical power-off proof.
4. At **ORA ACCENDI** (“switch on now”), restore power without holding buttons,
   then promptly press Enter. Scanning is already active.
5. The tool records the first target callback, stops scanning and connects for
   authenticated console status. If BlueZ has a pending connection it cancels
   only that target's attempt, retaining bonds and adapter state.
6. Review the interval bounded by the cue and your confirmation. It is valid
   only if power was restored between them. Adapter/scanning/connect latency is
   included; it is not electrical timing or pure bootloader time.
7. Compare pre/post uptime with request timestamps. A new kernel must be observed
   for success; otherwise the result is `restart_not_confirmed`.

A DK coin cell or another supply can keep VDD powered despite USB removal.
Exclude such sources through the approved bench setup **before** the trial;
waiting is not a method to discharge a battery. Default waits are not guaranteed
electrical discharge times. `electrical_power_off_confirmed` remains false.

## Results, timeout and recovery

Default timeout is 300 seconds for initial and post-cue BLE waits; change with
`--timeout 600`. `--off-seconds 120` and `--quiet-seconds 10` select the wait
requirements. No BLE connections are opened during the OFF pause; scanning stays
active. Timeout never authorizes the ON cue.

A new ignored `experiments/vimar-boot-timing-<UTC>/` holds UTC/monotonic events,
confirmations, retries and responses in `events.jsonl`; `results.json` updates
throughout. `--output` selects a new directory. Ctrl+C saves partial state.
Exit codes: 0 new startup observed, 2 restart unconfirmed/recovery detected,
1 error/timeout, 130 cancelled. No reset, upload, lamp command or automatic
restoration follows failure.

Bleak/BlueZ callbacks can include cached property changes. The historical JSON
field `first_advertisement` names that callback, not a certified HCI radio
timestamp. Authenticated uptime comparison supplies new-kernel evidence. If SMP
recovery appears instead of MAIN, the tool ends immediately as `recovery_detected`
without reset. Recovery reachability is not MAIN startup or electrical OFF;
verify its image hashes separately. One measured cycle is not boot reliability.
