# Opt-in common RESTORE admission gate — source/unsigned probe

Historical scope: this page records the initial unsigned probe and its host/native
validation. Later common-package integration is implemented, but the new generic
restoration route remains physically unqualified. See the
[current evidence summary](../../docs/research-summary.md#architecture-and-current-status).
Statements about pending consumers and unsigned outputs below describe that
original probe stage.

This new module defaults to disabled and is not included by current firmware
profiles. It leaves `firmware/restore_gate/` and the existing signed candidate
pair unchanged. It implements only the extra protection-exception decision;
it does not implement generic stock restoration, an Android anchor writer,
loader-family approval in runtime consumers, signing, deployment or physical
qualification. Do not enable a privileged consumer until its own anchor/page
checks have been reviewed.

## Exact trust boundary

The owner initial SWD installation and normal loader/anchor hardware protection
establish this common loader's authority. It does **not** compile its own code
family hash into itself. Future external main/recovery/migration/packaging
consumers must approve exact code-family digests under their explicit contract;
that separate integration remains pending.

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
The future generic RESTORE program must independently revalidate the anchor,
live UICR and anchored page table before the first write, and each page before
writing it. It must check the logical complete original-FLASH digest before
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
bytes are linked: future first-install software writes that data page only
after saving and verifying the original archive. The native helper additionally
checks all mapped HEX addresses and the complete physical partition map.

## Tests and actual unsigned native evidence

`tools/firmware/tests/test_common_restore_gate.py` has **96 passing tests**.
Its pure fixtures are independent Python wire bytes; shape tests deliberately
use fake crypto bytes and do not claim cryptographic proof. Separate ephemeral
real ECDSA/OpenSSL fixtures prove that valid signatures for other roles do not
authorize RESTORE, and corrupt payload/signature or wrong key cannot be replaced
by valid-looking role bytes. The SDK-shaped adapter test compiles the actual
adapter C with host stand-ins to check call order, cleared private state,
selection checks, UICR-error refusal, precise protection delegation and preserved
FIH result. It is explicitly separate from target CC310 execution.

Negative compile tests cover each mandatory/forbidden guard and non-SHA256.
Link tests use initialized-data-only images on both sides of the44KiB bound.
The original parser/admission stub failed50 semantic tests; the wrapper stub
failed27 adapter/config cases before implementation. All94 tests also pass
with undefined-behavior sanitization for the pure policy, and the adapter test
always uses UBSan. No production signing key is used by these tests.

Independent review found that the initial guard omitted `BOOT_GO_HOOKS` and
`BOOT_FLASH_AREA_HOOKS`. Those configurations now fail compilation and the
native probe's effective-config check. Both new negative cases first failed,
then passed after correction. The inspected earlier ELF already had these
hooks disabled; no bypass was established in that exact image. The fresh v3
unsigned probe uses the corrected source and still occupies27524 FLASH bytes,
with17532 bytes before the reserved anchor page. Earlier proofs remain intact.

Actual probe:

```sh
work/ncs-venv/bin/python tools/firmware/build_common_loader_probe.py \
  --output experiments/<new-empty-directory>
```

The helper accepts only an existing public-key PEM, builds only the MCUboot ELF
without sysbuild children or signing, and freezes a firmware source copy without
keys. Successful output:
`experiments/common-loader-admission-20261023-v2/`. V1's failed configuration is
preserved: directly assigning hidden `BOOT_USE_NRF_CC310_BL` is invalid, so the
helper uses the user-facing `BOOT_ECDSA_CC310` choice and verifies the resulting
hidden backend flags.

V2 native compile/link passes with **27524 bytes FLASH**, **15104 bytes RAM**,
leaving **17532 bytes** before the anchor. `_flash_used=0x6b84`; nonempty ELF
load segments have physical extents `[0,26988)`, `[26988,27520)`,
`[27520,27524)`. All are below `0xb000`, including initialized ROM data.
The complete physical layout still matches the existing48KiB boot partition.

`link-inspection.json` records SDK commit/source hashes and saved disassemblies.
Actual main contains `r1=49152`, `r0=0`, then calls `__wrap_fprotect_area`.
Wrapper disassembly calls real `boot_go` and `common_restore_admit` in order;
selected-slot validation calls `boot_image_validate`, then
`bootutil_img_validate`. This confirms the linked crypto call chain and
protection geometry, not a hardware signature-operation trial. No anchor,
signed loader, signed generic restorer or installable firmware set was produced.

Detailed probe counts and frozen review records remain local. The
[public evidence summary](../../docs/research-summary.md#architecture-and-current-status)
separates this historical native evidence from current physical qualification.
