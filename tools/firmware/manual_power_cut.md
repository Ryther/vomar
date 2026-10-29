# Manual DK power-cut during BLE upload

This destructive-to-the-test-application experiment requires explicit approval
for the isolated DK, selected signed MAIN and manual USB power cut. Disconnect
the Vimar completely. Have an independent recovery route and a known signed MAIN
ready; the DK remains in recovery after the test. Do not apply this procedure to
a mounted dimmer or assume a USB disconnect removes every power source.

Use the prepared BLE Python environment and existing BlueZ bond. The exact DK
address, expected active recovery SMP hash and complete MAIN file SHA-256 are
required:

```sh
python tools/firmware/manual_power_cut.py --address "$VIMAR_DK_BLE_ADDRESS" \
  --image "$VIMAR_DK_IMAGE" --image-sha256 "$VIMAR_DK_IMAGE_SHA256" \
  --recovery-hash "$VIMAR_DK_RECOVERY_SMP_HASH"
```

1. Enter recovery with DK B1 + RESET, release B1 and prepare the USB power cable.
2. Press Enter to start the reviewed upload.
3. At **STACCA ORA LA USB DEL DK** (“disconnect DK USB now”), disconnect it
   immediately. Upload continues after the cue; terminal sound depends on settings.
4. Leave the DK off until asked. Confirm only if you observed complete power loss.
5. Reconnect USB **without B1** when asked, then press Enter. The tool checks that
   the same authenticated recovery returned automatically.

The default cue follows 65536 acknowledged bytes; `--signal-at` accepts
4096–262144. If upload reaches 90% without interruption, the tool stops it and
does not pass the trial. Ctrl+C cancels without reset or automatic restoration.
An incomplete MAIN can require B1 + RESET. The helper does not modify loader or
recovery and sends no SWD commands. Restore MAIN afterward only through its
separately reviewed supported BLE upload flow; this helper does not do that.

Events, complete file hash, final acknowledged offset and operator confirmation
are stored in a new ignored `experiments/dk-manual-power-cut-*/events.jsonl`.
A BLE disconnect alone is not power-loss evidence. The manual cue follows an
ACK while upload continues; it does not measure an interruption during an exact
FLASH programming pulse or qualify all power-cut boundaries.

For synthetic host checks without hardware:

```sh
python -m unittest discover -s tools/firmware/tests -p test_manual_power_cut.py
```
