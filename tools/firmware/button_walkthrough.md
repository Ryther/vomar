# Check Vimar recovery-button gestures

This bench guide checks two recovery entrances on the historical BLE research
profile with a **simulated output backend**. It does not test front-button lamp
control, color/polarity or power-stage behavior. Before use, obtain explicit
operator approval for the exact target, manual power actions and reset back to
MAIN. Keep the approved isolated bench wiring; do not attach a DK to a live
mains-powered dimmer. Close other BLE clients.

Prepare an existing BlueZ bond and set the exact target BLE address and expected
MAIN/recovery SMP hashes (SHA-256 of the signed region, not the complete file):

```sh
python tools/firmware/button_walkthrough.py \
  --address "$VIMAR_BLE_ADDRESS" --main-hash "$VIMAR_MAIN_SMP_HASH" \
  --recovery-hash "$VIMAR_RECOVERY_SMP_HASH"
```

Use the prepared BLE Python environment from the [development guide](../../docs/development.md).
For instructions without BLE access, run:

```sh
python tools/firmware/button_walkthrough.py --plan
```

## Follow the terminal prompts

1. The tool checks the simulated MAIN over authenticated BLE without lamp commands.
2. Press Enter to arm. Wait for **ORA** (“now”), then hold both Vimar UP/DOWN
   buttons for at least six seconds and release. These are the Vimar buttons,
   not DK BUTTON 1 or RESET. Monitoring starts before the cue.
3. The tool authenticates recovery and verifies both image hashes. Confirm
   whether you performed the gesture. Release every button, then press Enter
   to authorize the SMP reset back to MAIN.
4. Arm the boot test with Enter. At **ORA**, disconnect the approved bench USB
   power, hold Vimar UP, reconnect power and keep UP held until the release cue.
   Leave the PC Bluetooth adapter connected.
5. The tool repeats authenticated recovery/hash checks and the reviewed return.

`SALTA` skips a test and records it incomplete. `Ctrl+C` stops and saves partial
results. The default timeout is 180 seconds for each BLE wait, including initial
MAIN and return; `--timeout 300` allows more time. Elapsed time includes reading
and reconnecting and is not a measurement of actual button hold duration.

## Read results and handle interruption

Each run creates a new ignored `experiments/vimar-button-check-<timestamp>/`
(`--output` selects another new directory). `events.jsonl` retains UTC events and
operator responses; `results.json` is refreshed after each phase and distinguishes
passed, skipped, unconfirmed, failed and cancelled outcomes. Existing results
are not overwritten. Exit codes: 0 both passed, 2 incomplete, 1 error, 130 cancelled.

A BLE timeout is not button evidence. After error, no further reset is sent;
the target may remain in recovery or may already have restarted during return.
Inspect `reset_request_sending` and `reset_acknowledged`, retain the report and
inspect current state before retry. The tool observes authenticated services and
hashes; operator confirmation is separate evidence. It does not upload firmware,
remove bonds or change adapter configuration.
