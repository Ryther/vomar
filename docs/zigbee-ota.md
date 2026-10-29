# Zigbee OTA contract and qualification

Zigbee OTA updates a compatible custom MAIN with a matching independent installer
recovery. It does not replace stock firmware initially, install a bootloader or
add OTA capability merely by loading a converter. Legacy pairs require explicit
supported migration. Use the client task guides for ordinary operations; this
page is for firmware/converter contributors and authorized bench operators.

## Signed carrier and admission

`package_zigbee_ota.py` creates a standard `.ota` carrier containing signed SDK
LZMA2 ARMThumb data with a 32 KiB dictionary. Protected model/hardware metadata,
compressed and plain signatures, roles, geometry and exact loader/pair contracts
must agree. The compressed source must fit outside the current running image
and its destination. The packager checks exact current/source/destination/page
budgets; a valid signature alone cannot admit an oversized carrier.

The independent BLE partition, loader authorization, UICR and network/settings
storage stay outside OTA write ranges. Version-independent
`vimar30805-split-v2` compatibility does not replace exact per-operation hash
verification. Keep those two checks separate when changing admission.

Download interruption requires another transfer, never permission to erase the
active application. Once pending, recovery reauthenticates and dry-runs the
source before primary erasure. Interrupted writes replay from the intact stage.
Crypto/storage errors stop installation; failure retains authenticated BLE
recovery. Warm output handoff is implemented, while measured lamp continuity
and physical power-cut behavior require separate evidence.

## Controlled Zigbee2MQTT trial

Require explicit approval for the exact target/artifact, a retained original and
an available recovery route. Use an isolated authorized bench deployment, not a
household service in tests. Configure the private OTA index in the Z2M runtime;
local image paths must resolve there. For an explicitly authorized direct trial:

```sh
python tools/firmware/qualify_zigbee_ota.py \
  --url wss://zigbee.example/api --ieee YOUR_DEVICE_IEEE \
  --image /absolute/path/to/release.ota \
  --output experiments/ota-trial/results.json
```

The runner resolves the current friendly name but sends the exact IEEE, records
progress and correlates the final response. `--origin` supports proxy checks;
`--cookie` selects a private credentials file (default
`work/private/z2m-cookie.txt`). Credentials stay out of reports/public source.
This command starts an update; its name is not proof that qualification succeeds.

A Z2M completed transfer does not establish installed image/hash, preserved
network/settings, BLE recovery, buttons, lamp or power-cut recovery. Collect
those separately. OTA cached version fields can lag direct-upload selection;
use the correlated final response and postboot evidence. See
[Zigbee controls](zigbee-controls.md#versions-and-verification).

## Guided initial installation and qualification gate

The legacy bench provisioning helper accepts `--ota-release` with a private
schema1 manifest. `ota_release.py` requires exact path/SHA-256 bindings for MAIN,
RECOVERY and qualification, signed versions, and literal true values for
`zigbee_ota_completed`, `postboot_hash_verified`, `ble_recovery_verified` and
`power_cut_recovery_verified`, before probing hardware.

For profile2 it additionally binds `pair_bindings`, matching recovery/allowed
loaders and true `split_stage_verified`, `loader_binding_verified`,
`recovery_tail_preserved`, `mixed_profile_rejected`,
`protection_flash_radio_verified`, `stock_restore_verified` and
`migration_verified`. This legacy pair schema differs from a schema3 common
package and the thirteen release qualification fields. Do not interchange them.

Validated bytes are frozen in the private device dossier before composition;
existing differing evidence is not overwritten. Missing qualification blocks the
route, not a reason to synthesize a report. Software-reset interruption does not
satisfy physical power-cut evidence. See
[provisioning](../tools/firmware/provision_vimar.md) and
[release qualification](releasing.md).

Retain original-stock backups and matching restoration material privately.
Stock restoration replaces custom firmware and has its own explicit review and
physical evidence scope; do not treat a carried helper as a qualified route.
