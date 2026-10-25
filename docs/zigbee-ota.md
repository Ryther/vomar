# Zigbee OTA — custom Vimar30805

Initial stock replacement still requires the DK/SWD procedure and a device-bound
original backup. This OTA client updates only a custom OTA-capable main paired
with the independent compressed-image installer recovery. Legacy0.5.1 devices
require that pair migration before using Zigbee OTA.

The external converter exposes standard OTA support. Release artifacts are
standard `.ota` files containing a signed SDK LZMA2 ARMThumb stream (32KiB
dictionary). Protected model/hardware metadata and compressed/plain signatures
are verified; the updater rejects a candidate that cannot fit alongside the
currently running image. The independent BLE partition, loader authorization,
UICR and network/settings storage are outside all OTA write ranges.

For a private image, use Zigbee2MQTT's custom firmware-file upload or the bounded
runner (Z2M's built-in hex upload writes the file under its private data/ota):

```sh
python tools/firmware/qualify_zigbee_ota.py \
  --url wss://zigbee.example/api --ieee YOUR_DEVICE_IEEE \
  --image /absolute/path/to/release.ota \
  --output experiments/ota-trial/results.json
```

The runner resolves the current friendly name from the selected Zigbee2MQTT endpoint,
uses the exact IEEE for the update request, shows progress and correlates the
final response. Cookie credentials stay in ignored work/private/z2m-cookie.txt.
It does not claim successful postboot qualification from Z2M's transfer response.
Normal availability checks can use the generated private OTA index once its
image URLs or local paths are installed on the Z2M server (never publish keys).

A downloading interruption restarts the transfer; it does not authorize erasing
the active application. Once pending, the independent installer reauthenticates
and dry-runs the source before primary erasure. Interrupted application writes
are replayed from the intact compressed stage. Failure returns to authenticated
BLE recovery. Operational crypto/storage errors stop installation rather than
bypass checks. Warm output handoff is retained; physical lamp continuity and
actual power-cut qualification require separate observations.

Current internal-flash budget is tight: each future signed release must pass the
packager's exact current-image/source/destination/page-budget checks. A signature
alone does not make an oversized candidate installable. Test releases on a bench
unit before distributing them to installed dimmers.

Original-stock BLE restore bundles remain per-device and replace the custom
firmware entirely. Keep both the original backup ZIP and its corresponding BLE
restoration ZIP in private cloud storage.


## Guided initial installation and qualification gate

`tools/firmware/provision_vimar.py --ota-release /absolute/path/pair.json`
selects a signed ordinary main/recovery BIN pair for a new device. It preserves
the existing per-device double backup, stock-restoration package, loader gate,
exact UID checks and full FLASH/UICR readback. It does not migrate an already
installed mains-powered device through SWD.

The private schema1 pair manifest contains `main`, `recovery` and `qualification`
records, each with `path` and exact `sha256`. Main and recovery also specify the
signed `version` (for example `0.5.3+0` and `0.7.1+0`). The qualification JSON must
have schema_version1, exact `main_sha256`/`recovery_sha256` matching the image
records, and literal true values for `zigbee_ota_completed`,
`postboot_hash_verified`, `ble_recovery_verified` and
`power_cut_recovery_verified`. A missing or incomplete report is rejected before
any hardware probe. The report is trusted local experimental evidence, not a
replacement for actually carrying out these checks.

Validated image bytes are frozen into the per-device dossier before composing
its installation HEX. Existing evidence with different bytes is not overwritten.
The legacy installation default remains unchanged until the OTA pair's physical
qualification is complete. Current software-reset interruption tests do not
satisfy the physical power-cut field; no qualified fleet manifest has been
issued yet.


The converter forwards numeric bounds to zigbee-herdsman's custom-cluster
metadata as well as its exposes. This is necessary for full-scale RGB255: the
installed10.9.2 decoder treats UINT8 FF as NaN unless max255 is explicit. This
compatibility correction does not change the firmware wire types or public
property names. Its regression test executes the version-pinned decoder when
the local qualification source archive is present.
