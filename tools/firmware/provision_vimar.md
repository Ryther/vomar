# Bench provisioning with a device-bound original

This advanced helper replaces nRF52840 FLASH while retaining the secondary
power-controller firmware. Use only a separately authorized bench dimmer attached
to an identified DK, disconnected from mains. Never connect the DK to an installed
mains-powered unit. For the native client workflow use
[Android first installation](../../docs/android-first-install.md) or
[desktop](../../docs/desktop.md); this helper uses a distinct legacy pair/dossier
contract and is not a substitute for their retained-session machinery.

## Prepare the target and artifacts

Install the pinned SDK/Python environment, OpenOCD/J-Link access, `intelhex` and
existing approved signing inputs. Close other SWD monitors/debuggers. Set the
local DK FICR DEVICEID in address order as `UID0:UID1`, eight hexadecimal digits
per word. Pass `--dk-id` for every connectable DK or set comma-separated
`VIMAR_DK_DEVICE_IDS`. Do not put the dimmer UID in that exclusion list. Missing
local exclusions block all hardware access.

A programming invocation requires explicit operator approval for the exact
target, signed artifacts and bootloader/FLASH writes. Then select the qualified
pair manifest explicitly:

```sh
python tools/firmware/provision_vimar.py --serial SERIAL_DK \
  --dk-id "$VIMAR_DK_DEVICE_ID" --ota-release /absolute/path/to/pair.json
```

There is no implicit application default. `ota_release.py` validates schema1,
exact hashes, signatures and physical qualification before probing. Profile2
requires its additional exact pair/loader and split checks. See
[OTA qualification](../../docs/zigbee-ota.md#guided-initial-installation-and-qualification-gate).
Do not select a newest filename or invent a qualification report to bypass it.

## What the helper does

It requires three identical external target identity reads, excludes configured
DKs and displays UID/candidate IEEE. Searching original FLASH for little-endian
IEEE bytes is a correlation, not a decoder of active Zigbee state or commercial
model proof. An independent known inventory can confirm the mapping.

Each UID gets a new private `experiments/provisioning/UID/timestamp/` dossier:

1. Halt for two coherent FLASH (1 MiB), UICR and FICR captures; compare copies,
   hash them and create `stock-backup.zip`.
2. Build device/original-bound signed restoration/bootstrap/loader authorization;
   validate signatures, partitions and known UICR/DC/DC constraints. Create
   `ble-stock-restore.zip` **before** permitting installation.
3. Freeze the qualified MAIN/recovery pair and initialized-storage installation
   image. The restoration helper remains UID/original-specific.
4. Display the plan and request the target IEEE as confirmation.
5. Recheck UID/original/UICR/images, program only required sectors without recover
   or mass erase, then read back complete FLASH/UICR.
6. Request boot only after full verification and keep all evidence. Requested
   boot is not autonomous startup or functional qualification.

## Backup, preparation and interrupted work

For a backup only, authorize the temporary processor halt separately; no firmware
selection, build, FLASH/UICR programming or erase occurs:

```sh
python tools/firmware/provision_vimar.py --serial SERIAL_DK --dk-id "$VIMAR_DK_DEVICE_ID" --backup-only
```

`--prepare-only` prepares evidence/artifacts and leaves the CPU halted. `--resume`
selects an existing dossier without overwriting complete backups. Incomplete
attempts stay in `partial/`. After partial programming, mismatch against the
original blocks ordinary continuation for diagnosis; there is no automatic erase
or blind retry. A verified install stopped before boot remains an operator
decision. Errors can leave the target halted: inspect the named dossier first.

```sh
python tools/firmware/provision_vimar.py --serial SERIAL_DK --dk-id "$VIMAR_DK_DEVICE_ID" --ota-release /absolute/path/to/pair.json --prepare-only
python tools/firmware/provision_vimar.py --serial SERIAL_DK --dk-id "$VIMAR_DK_DEVICE_ID" --ota-release /absolute/path/to/pair.json --resume /absolute/path/to/session
```

The helper has a noninteractive mode only for an already authorized exact device:
`--expected-id UID0:UID1 --yes`. This flag is not universal native-client consent.
The explicit legacy `--main /absolute/path/image.hex` option uses old BLE recovery
and does not install the required Zigbee OTA pair; never use it to evade pair
qualification.

## Local configuration and retained material

| Variable | Meaning |
| --- | --- |
| `VIMAR_JLINK_SERIAL` | Local probe serial |
| `VIMAR_OTA_RELEASE` | Explicit pair manifest |
| `VIMAR_DK_DEVICE_IDS` | DK UID exclusion list |
| `VIMAR_NCS_WORKSPACE` | Prepared pinned SDK workspace |
| `VIMAR_BUILD_PYTHON` | Build/imgtool Python |
| `VIMAR_WEST` | SDK west executable |
| `VIMAR_SIGNING_PRIVATE_KEY` | Existing approved ECDSA-P256 private key path |
| `VIMAR_SIGNING_PUBLIC_KEY` | Matching public key path |

Use absolute local paths. Build defaults live under ignored `work/`; private
keys never enter ZIPs. Restoration cache rejects a differing configured public
key: do not mix retained restoration packages and a replacement trust root.
The helper needs no Zigbee2MQTT credentials and an instance lock prevents two
copies, though other debuggers must still be closed manually.

## Verify and retain after provisioning

Before mounting, independently check autonomous startup without debugger,
BLE recovery entrances/return, join/rejoin, buttons, lamp and restoration scope
for the exact signed set. For an existing Z2M entry, re-interview **and Configure**
the exact IEEE (`bridge/request/device/interview`, then
`bridge/request/device/configure`). Interview alone can leave the server's
custom-cluster metadata stale and produce `UNSUPPORTED_CLUSTER vimarDimmer`.

Keep both stock-backup and matching BLE restoration ZIPs in protected external
storage. They contain device/network data and stay out of Git/public artifacts.
A restoration ZIP's README describes its exact route; its existence is not proof
of a successful restoration trial. Full stock restoration replaces custom
firmware and requires its own explicit approval. Preserve original evidence,
journals and signer continuity; passing source checks does not qualify the device.
