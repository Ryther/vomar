# Common RESTORE admission gate

This opt-in nRF52840 MCUboot module permits one precise boot-protection exception
for a signed RESTORE-role image and a committed local backup anchor. It is wired
by the common-candidate builder and remains disabled in ordinary configurations.
The older [exact-restorer gate](../restore_gate/README.md) is separate and cannot
be enabled simultaneously. Current consumers include the
[common restorer](../common_restore/README.md) and
[first-install contract](../../tools/android/first_install_contract/README.md).
Their physical qualification remains separate from integration and signing.

## Exact trust boundary

The owner initial SWD installation and normal loader/anchor hardware protection
establish this common loader's authority. It does **not** compile its own code
family hash into itself. External main/recovery/migration/packaging consumers approve exact code-family
digests under their explicit typed contract; the loader does not approve itself.

`__wrap_boot_go` clears its private authorization on every call, then invokes
`FIH_CALL(__real_boot_go, ...)`. Only fresh real FIH success with actual flash
device0 and selected image offset `0xb0000` may proceed. It reads live local
FICR identity/geometry and hashes the 4096-byte UICR through the SDK SHA256
backend. It then requires the selected ordinary image's strict protected
RESTORE/profile2 policy and the committed anchor's live identity/UICR match.
Retained entrance requests, headers or role bytes alone grant no exception.

The pure parser requires MCUboot magic, zero load/flags/reserved fields,
512-byte header, bounded ordinary extent below `0xef000`, valid aligned MSP
and Thumb reset inside the selected payload. Every TLV header **and payload**
must fit its area. Protected metadata permits exactly one target
`VIMAR30805\x02`, exactly one shared `OTA_IMAGE_ROLE_RESTORE` value4 in a
one-byte `0xA1`, and at most one length4 security counter. Unknown protected
metadata, duplicates, wrong/missing roles, target mismatch and unprotected
role/target reject admission. Ordinary hash/key/signature TLVs must have the
expected shape and uniqueness. Their bytes are not reverified by this parser:
actual signature verification is the real SDK boot result's responsibility.

The parser stages outputs until input consumption completes. The admission
helper has no output publication or flash callbacks. Its `real_boot_validated`
argument is a trusted adapter precondition, never a protocol/request field.

Additional admission failure preserves the real boot result and normal loader
protection. It does not introduce a global halt for a missing/invalid anchor.
The generic RESTORE program independently revalidates the anchor,
live UICR and anchored page table before the first write, and each page before
writing it. It checks the logical complete original-FLASH digest before
the final SRAM-only boot replacement; the complete backup cannot be buffered
in the target's RAM before all page writes.

`__wrap_fprotect_area` may omit only the exact call `(0,0xc000)` after private
admission succeeds in the same boot. Every other region and every failure calls
the real protection function and propagates its result. SDK main stops startup
on protection failure. No ACL-unlock API exists: the decision precedes hardware
programming. Ordinary boot covers both code and anchor.

## Configuration and reservation

The compile guard requires the audited nRF52840 firmware-loader path, fresh
`BOOT_VALIDATE_SLOT0`, ECDSA-P256 with the existing CC310 BL backend, SHA256,
FIH OFF, FPROTECT and MCUboot's unprotected-TLV allowlist. It rejects ONCE or
signature-none/key bypass/lifecycle test paths, unaudited boot hooks, encrypted,
compressed or swap modes, alternate key authorities and simultaneous legacy
wrappers. CMake also rejects a simultaneous enabled old restore gate. These are
intentional restrictions to the inspected SDK configuration, not a portability
promise. FIH APIs with profile OFF do not claim fault-injection hardening.

The physical loader partition stays48KiB (`0..0xc000`); app/recovery/settings
addresses do not move. The link assertion requires `_flash_used <= 0xb000`,
including ROM load images of initialized data and RAM functions. No anchor
bytes are linked: first-install software writes that data page only
after saving and verifying the original archive. The native helper additionally
checks all mapped HEX addresses and the complete physical partition map.


## Inherited watchdog handoff

`CONFIG_VIMAR_INHERITED_WATCHDOG_HANDOFF` adds the reviewed early loader hook.
For the signed `paused-reset-before-main-v1` capability and admitted live profile,
first installation captures with the watchdog paused on HALT and ends halted.
A separate verified start lets the loader wait for a genuine watchdog reset
before ordinary boot, without feeding the inherited watchdog. Inactive WDT adds
no delay. The option alone grants no install/start authority.

## Verify the gate

```sh
python -m pytest tools/firmware/tests/test_common_restore_gate.py
```

Independent synthetic wire fixtures check strict image/anchor parsing. Separate
real ephemeral ECDSA fixtures exercise role/signature boundaries; SDK-shaped host
adapters check call order, cleared authority and precise protection delegation.
Compile/link checks enforce mandatory configuration and the 44 KiB code limit,
including initialized ROM data. Source/host tests do not execute target CC310,
prove physical protection or qualify interruption recovery.

For an unsigned native link probe with a prepared pinned SDK:

```sh
python tools/firmware/build_common_loader_probe.py --output experiments/new-common-loader-probe
```

Use a new output directory. The probe builds MCUboot ELF with a public key,
records link inspection and checks mapped HEX bounds. It produces no signed
installable set and performs no hardware operation. Exact historical sizes and
counts are properties of the recorded probe, not budgets for a later build.

## Historical unsigned probe (2026-10-23)

The corrected native probe occupied 27524 FLASH bytes and 15104 RAM bytes;
`_flash_used=0x6b84` left 17532 bytes before the anchor page. Mapped initialized
data/RAM-function load extents also remained below `0xb000`. Linked inspection
confirmed the real boot validation chain and exact `(0, 49152)` protection call.
This measured one unsigned source snapshot, not a signed deployable set.

Review added rejection of `BOOT_GO_HOOKS` and `BOOT_FLASH_AREA_HOOKS`; both new
negative cases failed before correction. The previously inspected ELF already
had those hooks disabled, so no bypass was established in that exact ELF.
Historical parser/adapter/configuration suites reported 96 passing tests; these
counts are dated observations and must not stand in for running current suites.
