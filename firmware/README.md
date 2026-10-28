# Vimar 30805 firmware

The nRF52840 application implements Zigbee On/Off and Level Control, configurable
local gestures, timer and power-on policy, layered LED behavior, persistent
settings, fault diagnostics and manufacturer cluster `0xFC00`. A separate DK
simulator supports development without the Vimar power stage. The Vimar adapter
uses recovered PWM/GPIO behavior and a conservative candidate P0.31 protection
monitor; it does not report physical lamp measurements or power-stage
acknowledgement. Electrical protection coverage remains unresolved.

Read [`VERSION`](VERSION) for this checkout's native firmware version and the
exact release manifest for shipped component versions. The distribution tag is
not the firmware version or a qualification claim. APS-105-5241 remains unresolved.
Historical DK and Vimar trials apply to their recorded images and routes; all
thirteen flags on the experimental common candidate remain false. See the
[research and evidence summary](../docs/research-summary.md).

## Connection selector and Zigbee pairing

The source implements a five-second two-button selector, bounded two-minute
Zigbee pairing and an explicit authenticated Bluetooth request. See
[Connection modes](../docs/connection-modes.md) for colors, network replacement,
timeouts and compatibility limits. It requires matching MAIN/recovery;
implementation alone does not establish physical qualification.

## Build dependencies

Use the pinned [development environment](../docs/development.md). From the
repository root, install the frozen SDK graph with:

```sh
python tools/dev/bootstrap.py firmware
```

[`west.yml`](west.yml) and `tools/dev/` own the exact Nordic/Zephyr revisions;
do not replace the frozen graph with an unrestricted upstream `west update`.
The examples below assume a local west workspace at `work/ncs-workspace`;
substitute your prepared workspace and build paths consistently.

Use the repository's absolute `firmware` directory as the application source if
your west workspace is elsewhere. Builds need a matching local signing setup;
only the public research key is distributed. See [key handling](keys/README.md).
An independently generated key creates a different trust root and does not sign
updates accepted by devices using this project's existing public key.

## Profiles and outputs

The base BLE profile, Zigbee DK simulator and independent-recovery profile are
separate build configurations. From `work/ncs-workspace`, build without device
access:

```sh
# Base BLE profile
west build --sysbuild -b nrf52840dk/nrf52840 ../../firmware \
  --pristine -d ../build-ble-dk

# Zigbee DK simulator
west build --sysbuild -b nrf52840dk/nrf52840 ../../firmware \
  --pristine -d ../build-zigbee-dk -- -DEXTRA_CONF_FILE=zigbee_dk.conf

# Independent BLE recovery and Zigbee main
west build --sysbuild -b nrf52840dk/nrf52840 ../../firmware \
  --pristine -d ../build-ota-zigbee-dk -- -DFILE_SUFFIX=ota
```

The opt-in `ota` profile uses an independent signed BLE updater, selected by DK
Button 1 during reset or an invalid primary image. It advertises as
`Vimar30805-Rescue` and uses authenticated SMP. The fixed development pairing
code `824005` is public research configuration, not a production credential.
This single-primary-slot profile offers independent recovery; it does not keep
a previous application image for automatic rollback. A hung signed application
can require the reset/recovery trigger. No Vimar recovery pin mapping follows
from the DK button mapping.

From the repository root, validate the generated recovery profile:

```sh
work/ncs-venv/bin/python tools/firmware/validate_recovery.py \
  --build-dir work/build-ota-zigbee-dk \
  --imgtool work/ncs-workspace/bootloader/mcuboot/scripts/imgtool.py \
  --key firmware/keys/dev-public.pem
```

The merged HEX includes loader/recovery/application and belongs to initial
provisioning. It is not an application-update file. An ordinary BLE update uses
the signed application or matching DFU ZIP; compressed Zigbee OTA uses its own
signed carrier and matching installer. Build outputs belong under ignored
`work/` or `experiments/`, not Git.

## Hardware application and common packages

The [BLE research application](research/README.md) supplies authenticated
instrumentation and the recovered PWM/GPIO backend. The main Vimar adapter is
[src/platform_io_vimar.c](src/platform_io_vimar.c). Current common packages bind
MAIN, recovery, migration, loader and restoration helpers through protected
role/profile metadata, exact hashes and finite loader contracts. The candidate
builder is [build_typed_common_candidate.py](../tools/firmware/build_typed_common_candidate.py);
its native builds require a prepared local SDK and signing environment.

The current schema3 candidate is shared by compatible devices; originals and
transaction checkpoints stay private and device-specific. Ordinary fleet and
release validators reject qualification candidates. Initial phone/DK installation,
explicit interrupted-install repair and a separate verified start are documented
in [the Android installation guide](../docs/android-first-install.md).

The original [dedicated restore gate](restore_gate/README.md) and the newer
[common restore engine](common_restore/README.md) have different evidence scopes.
A historical full Vimar stock restore succeeded with the dedicated path; the
new common-loader/generic helper route remains physically unqualified.
Android has an explicit stock-restoration flow using the retained matching
original; carrying signed helpers alone does not qualify that workflow.

See [Zigbee OTA](../docs/zigbee-ota.md), the
[Zigbee2MQTT converter](../integrations/zigbee2mqtt/README.md) and
[loader contracts](loader_contract/README.md) for their respective interfaces.
Physical programming, bootloader writes, erasure and UICR writes require explicit
operator approval; the commands above only build and inspect local files.

## Host checks and optional local integration checks

From the repository root, with the Python dependencies listed in the
[main README](../README.md), run:

```sh
PYTHONPATH=. python3 -m pytest tools/firmware/tests -rs
```

Portable unit and host-C tests stay active in a public checkout. Tests consuming
absent private originals, archived exact images/manifests, a matching local
private signing key or native SDK artifacts skip only their dependent cases;
`-rs` shows the missing-input reasons. Never publish the matching private key
to make such a test run. SDK-dependent checks cover actual imgtool/zcbor,
compression decoding and reviewed ZBOSS headers; set `VIMAR_NCS_WORKSPACE` for
a prepared local SDK workspace. These optional checks and historical artifact
checks remain separate from physical qualification.

## Wired auxiliary push-button candidate

The source now includes the previously omitted wired-input path. Conventional
push buttons connected to terminal P share one auxiliary input; they are separate
from front UP/DOWN buttons and from Bluetooth Mesh/radio accessories. The stock
Zigbee trace uses a pulse-qualified input and one-button dimmer behavior. The
candidate provides short-press toggle, long-press dimming while already ON,
alternating direction after long release, and stop on release. Configured level
limits, hold timing, step size, auto-off and output protection still apply.

A button held at startup, through connection selection or across an external
command must release before another action. Auxiliary presses never enter the
connection selector. They do not masquerade as front UP/DOWN gesture events or
add a new persistent setting. Mesh scene assignment and radio accessory pairing
are separate features and are not implemented by this change.

On one installed Vimar running the exact signed MAIN 1.1.3 candidate, the
operator reported successful short toggle, long-press dimming, release-to-stop
and alternating direction with all four wired buttons. The preceding OTA and
correlated readback verified the version, unchanged recovery and all 40 settings.
This is bounded operator-observed acceptance; no terminal waveform or physical
MAIN hash was measured, and broader hardware/release qualification remains open.

## Front holds, phase-cut selection and Identify (schema 8 candidate)

A front UP or DOWN long press dims only a lamp that is already ON with an
applied ON output. Holding either button while OFF keeps it OFF, including
an initial ON delay or an unfinished OFF ramp. The release does not become a
short click. The separate wired auxiliary input keeps its existing behavior.

`phase_cut_mode` selects `trailing_edge` (TE, wire value 0) or `leading_edge`
(LE, wire value 1). The default is TE, including migration of older records without a phase field.
An explicit `CONFIG_RESEARCH_STOCK_CONFIG19=1` build override selects LE.
The selection uses P0.19 while retaining the stock secondary power controller.
A change requires accepted, target and applied output to be OFF with no pending
delay or ramp. It is saved durably before applying the GPIO; a storage failure
leaves the mode unchanged. An unexpected hardware apply failure inhibits output
and reports an output fault. No automatic retry or restart is performed.

Settings record v5 appends the phase choice and reads v1–v4 without discarding
their values. Older firmware cannot decode v5: a downgrade is not a settings
migration and must not be assumed to preserve configuration. Warm recovery
returns preserve P0.19 when it matches the loaded choice; cold starts load that
choice before enabling output. If a warm ON return inherits a different phase
(for example from older settings without a phase field), startup inhibits the
output and reports a fault without switching phase under load. The failed
adapter does not authorize ON. A fresh OFF initialization is required after
review; there is no automatic retry.

The standard Identify command controls a temporary green LED flash at 5 Hz.
The converter's Identify button requests 15 seconds; IdentifyTime=0 cancels it.
A fault indication has priority. On expiry the configured LED profile or an
unexpired manual override returns. Identify never changes the lamp or saves LED
configuration. Repeating Identify during an active SDK countdown can shorten
the renewed interval by less than one second.

These behaviors have host-test coverage. Electrical phase-cut behavior,
load compatibility and mounted-device timing still require physical validation;
software tests alone do not qualify this candidate.

## Original SDK error diagnostics

`CONFIG_VIMAR_FAULT_DIAGNOSTICS` requires the pinned SDK, an immutable build ID,
settings storage and reset-on-assert. It registers an application error callback
before application Zigbee setup. The callback retains the original signed SDK
error code and severity before a later generic assert such as `116:81`. MINOR
severity `1` is recoverable in the pinned SDK archive and does not consume the
first-cause slot. The inspected production link has MAJOR/FATAL direct callers;
its optimized raiser omits the unused MINOR branch. The callback always returns
false, preserving normal SDK error handling.

For FATAL severity `255`, the callback copies the documented verifier file ID and
signed line only when the additional-info pointer is aligned and the two fields
fit within nRF52840 SRAM. It never follows the caller's additional-info pointer.
An invalid pointer produces a record without an original location. SRAM bounds
protect field reads; they do not prove that damaged in-range data is truthful.
No allocation, logging, SDK service, settings or flash operation runs in this
callback. Existing bounded interrupt masking protects the RAM journal.

The 128-byte v1 format, ERROR kind `2`, CRC, reserved words, first-cause policy and
eight opaque export chunks remain unchanged. The numeric `source` token reserves
these namespaces (all examples are synthetic):

| Source token | Line field | Meaning |
| --- | --- | --- |
| `0xA0ss0000` | `INT32_MIN` | SDK severity `ss`, original location unavailable |
| `0xA1FFffff` | Original signed line | FATAL verifier file ID `ffff` |

For example, source `0xA1FF007C`, line `652`, error `-29` records the original
verifier location. Source `0xA0FE0000`, line `INT32_MIN`, error `-2305` records a
MAJOR error without a verifier location. The valid LINE bit in the latter case
marks the sentinel, not an observed original line. Old v1 readers preserve the
raw values. Existing checked-error site IDs `1` and `2` retain their meaning.

Decode a previously saved JSON export without accessing hardware:

```sh
python -m tools.firmware.read_fault_diagnostics exported-state.json \
  --build-id <32-hex-character-archived-build-id>
```

The decoder reports recognized records as `sdk_error`, retaining raw fields and
build identity. `original_location_present` distinguishes a captured verifier
location from the sentinel. Unknown or inconsistent tags remain uninterpreted
`checked_error` records; integrity checks still apply. Match the stored build ID
to its archived ELF, including when a newer firmware exports older evidence.

Persistence occurs at healthy next startup: settings save and independent
readback precede acknowledgement of retained SRAM. Earlier unacknowledged
records intentionally block replacement. Capture starts after SDK initialization
and journal setup; earlier errors, lost SRAM on power failure and failures before
callback entry can remain unobservable. This diagnostic change cannot recover
missing origins from old `116:81` records or establish their relationship to an
APS ownership error.

## Recovery compatibility across releases

From source candidate 1.1.6, MAIN admits the stable signed RECOVERY/profile2
update contract independently of recovery version or file hash. The same MAIN
image works with compatible older and newer recoveries; no per-device package
or enumerated recovery-version list is needed. The temporary 1.1.5 pin list is
superseded. Existing signed artifacts and installed recoveries are unchanged.

Admission still requires the approved loader/anchor, pinned project signing key,
model `VIMAR30805`, authenticated role RECOVERY, profile2, slot bounds and valid
recovery vectors. Profile2 freezes the split-staging layout, journalV2 and
32 KiB LZMA2/ARMThumb update format. An incompatible ABI requires another signed
profile and an explicit migration. Unsupported or roleless experimental
recoveries do not gain admission by version comparison.

Each boot captures the actual authenticated recovery and loader identities.
First-block admission and final CHECK reject a change to either; the immutable
boot recovery extent defines staging bounds. JournalV2 then pins the actual
full-file recovery and full48KiB loader hashes, which the installer verifies
again before writing. Exact operation verification never falls back to generic
contract admission. Read-only runtime identity continues to use the distinct
signed-region/SMP hash.

The canonical candidate builder checks the actual recovery configuration before
signing profile2 and emits MAIN bindings without a recovery-version pin. Host
regressions exercise different signed recovery versions, unknown/wrong contract
rejection, changed in-flight identities and exact journal preservation. These
checks do not establish physical power-cut or electrical qualification.
