# Typed loader and backup-anchor contract

This reference describes the portable C authority used by opted-in firmware and
host tooling. `firmware/CMakeLists.txt` includes `runtime.cmake`; enabling
`CONFIG_VIMAR_LOADER_RUNTIME_V2` requires an explicit finite bindings header and
an existing authenticated image verifier. The core itself supplies no FLASH
writer, signature verifier, protection exception or hardware reset.

Typed loader approval and live anchor validation are separate from exact
per-operation image/hash binding. See [runtime integration](LOADER_RUNTIME.md),
[common restore gate](../common_restore_gate/README.md) and
[first-install contract](../../tools/android/first_install_contract/README.md).

The canonical anchor is one 4096-byte page at `0xb000..0xc000`. All multibyte
integers are little endian. There are no caller-selected address fields.

| Offset | Bytes | Value |
| --- | --- | --- |
| 0 | 4 | ASCII `VAR1` |
| 4 | 2 | Format version 1 |
| 6 | 2 | Header length 256 |
| 8 | 4 | Loader contract 1 |
| 12 | 4 | Physical layout 2 |
| 16 | 4 | MCU part `0x52840` |
| 20 | 4 | Live MCU variant |
| 24, 28 | 4 each | Live FICR UID words 0 and 1 |
| 32 | 4 | FLASH size `0x100000` |
| 36 | 4 | Page size `0x1000` |
| 40 | 4 | RAM size `0x40000` |
| 44 | 4 | UICR size `0x1000` |
| 48 | 4 | Page-hash table size `0x2000` |
| 52 | 12 | Bytes `VIMAR30805\0\0` |
| 64 | 32 | Original FLASH SHA256 |
| 96 | 32 | Original UICR SHA256 |
| 128 | 32 | SHA256 of canonical 8192-byte page-hash table |
| 160 | 88 | All `0xff` |
| 248 | 4 | IEEE CRC32 of bytes `0..247`, zlib-compatible |
| 252 | 4 | Commit marker `0xa60c17ed` |
| 256 | 3840 | All `0xff` |

`loader_anchor_encode` creates the complete canonical page in **RAM**. The
first-install writer must program/readback-verify the body with commit erased, then
program the four-byte commit word last. The core supplies no flash writer.
`loader_anchor_decode` requires exactly 4096 bytes, all fixed/reserved values,
CRC/commit, and locally supplied live part/variant/UID/geometry/UICR hash. It
publishes a zeroed output on failure. Decode and authorization stage results
locally and publish or zero only after consuming all input. Outputs may alias
the source page, live expectations or compatibility records; output writes
cannot erase a trusted comparison input before validation. Its original FLASH/table hashes are
recorded authority for later checking; decoding does not verify those original
bytes. CRC is integrity, not a project signature. The separate loader/physical
installation must establish and protect anchor authority.

## Exact compatibility records

The family hash is SHA256 of the following exact byte sequence:

1. ASCII `VIMAR30805-LOADER-CODE44K-ANCHOR1` followed by exactly one NUL;
2. all `0xb000` bytes of loader code/padding from FLASH offset zero.

`loader_contract_family_digest` streams that fixed span in 256-byte chunks.
`loader_contract_full_digest` computes the unchanged legacy SHA256 of exactly
`0xc000` bytes without a prefix. No API accepts masks or ignored regions.

`loader_contract_authorize` accepts 1–64 explicitly typed records:

- `LOADER_CONTRACT_LEGACY_FULL48K_SHA256`: require the exact entire 48 KiB hash.
  It intentionally preserves legacy semantics and does not interpret an anchor.
  Its returned anchor is zero. It grants no new identity/protection authority.
- `LOADER_CONTRACT_COMMON_CODE44K_ANCHOR_V1`: require the exact approved family
  hash, then read/decode the complete fixed anchor page and compare live local
  identity/geometry/UICR. Any malformed anchor rejects this route.

Unknown record types, unknown digests, short reads and read/hash failures reject
authorization without publishing a partial result. Changing data outside the
one fixed anchor page changes the family hash. Two different properly
initialized units can share a common-code digest while having distinct UID,
backup hashes and complete 48 KiB hashes. A new common-code digest still needs
explicit release approval; there is no acceptance of unknown loaders.

Reader bytes remain immutable for one whole operation. Caller-owned crypto
callbacks provide SHA256 begin/update/finish/abort, with serialization owned by
the caller. Positive callback results become `-EIO`; negative errors propagate.
Abort runs after every begin attempt, including begin failure and successful
finish. The core itself depends only on standard C memory functions; it has no
crypto implementation or key material.

## Authenticated RAM page table

A `loader_restore_session` owns its anchor and an 8192-byte table. Initialize
only from a successfully decoded/authorized anchor. Table entry `i` is SHA256
of original FLASH `[i*4096,(i+1)*4096)`, with 256 ascending entries.

`loader_restore_table_accept` owns/copies the input, hashes its exact length,
and requires the anchor table hash. It also requires each of the **63** table
entries for the existing restorer scratch range `0xb0000..0xef000` to equal
SHA256 of an all-FF 4096-byte page. Thus a correctly anchored table for an
unsupported non-erased original scratch region is rejected too. In-place
acceptance using the session's own table buffer is supported.

A rejected pre-write retry invalidates/zeros the table. Once
`loader_restore_begin_write` succeeds, all table-accept calls return `-EBUSY`
without changing the accepted bytes. Reset clears the entire session; it must
be initialized again and the table must be resent/reverified before further
use. Callers must serialize access and treat session memory as trusted private
state, rather than a directly writable BLE upload buffer after acceptance.

`loader_restore_page_matches` requires accepted metadata, an exact 4096-byte
page and aligned in-range address outside scratch. It computes real SHA256 and
compares the appropriate accepted table entry. It supports original boot-page
checks for later SRAM staging, but has no flash callback or finalizer. Page
checks may run before begin-write for query/dry-run; an actual writer must
explicitly require successful begin-write and page verification. This library
cannot enforce correct use by a hardware adapter.

The [common restorer](../common_restore/README.md) checks staged pages,
reconstructs/hashes logical whole original FLASH against the anchor, rechecks
UICR and uses an SRAM-only finalizer after quiescing execution. These consumers
are implemented; physical qualification remains separate.


## Verify changes

From the pinned development environment:

```sh
python -m pytest tools/firmware/tests/test_loader_contract.py
```

The suite uses independent Python `struct`/CRC/hash fixtures and host crypto
callbacks, including aliasing, malformed anchors, exact digest domains,
identity/UICR mismatches, table/page authority and write-lock failures. Host
checks establish the portable contract, not target timing, FLASH protection or
power-loss recovery. Native link/fit checks belong to the matching builder;
physical qualification must identify the exact signed executable set.

## Historical portable-core evidence (2026-10-23)

The corrected isolated core passed 93 focused tests, including a UBSan run.
The recorded Cortex-M4 Thumb `-Os` object used 2383 bytes of text and no data/BSS,
with only standard memory functions unresolved. Measured local frames were
952 bytes for authorization and 320 bytes for streaming hashing; these are not
whole-call-chain or adapter/crypto stack budgets.

Review found that eager output clearing could corrupt an aliased trusted UICR
comparison input. Staging input consumption before output publication corrected
that defect; the independent reproducer rejected the mismatch afterward, with
nine regressions covering invalid and valid overlap. This is historical
host/object evidence, not proof that a linked production loader fits or that
physical installation/restoration is qualified.

## Version-independent recovery admission and exact operation identity

`loader_pair_authenticate` admits a signed RECOVERY role2/profile2 image after
loader/anchor, project-key, model/profile, extent and vector validation. Recovery
SemVer and file hash are outputs, not compatibility selectors. Profile2 denotes
the stable split-staging/journalV2/32KiB LZMA2+ARMThumb update ABI; breaking that
ABI requires a distinct signed profile and migration. It grants no write action.

`loader_pair_verify` is the separate exact operation check. It requires a
non-null expected full signed-file hash and rejects a different otherwise valid
recovery. Recovery installation still calls that exact API using journalV2;
there is no fallback to contract admission on mismatch. Both paths stage results
before publication and clear outputs on failure. MAIN freezes its boot recovery
extent and actual recovery/loader hashes, rechecking them before staging writes
and before publishing the pending transaction. Ordinary MAIN OTA changes neither
recovery nor loader. Legacy full48KiB loader authority retains its exact meaning.
