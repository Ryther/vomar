# Portable loader/backup-anchor contract v1

This source-only core is opt-in: no existing firmware CMake target includes it.
It does not select an image, verify a firmware signature, program flash, control
ACL protection, reset hardware or extend existing loader allowlists. Existing
main/recovery/migration/restore consumers are unchanged. Integration must retain
successful MCUboot validation and explicit privileged RESTORE authorization
before any protection exception.

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

`loader_anchor_encode` creates the complete canonical page in **RAM**. A future
SWD installer must program/readback-verify the body with commit erased, then
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
cannot enforce correct use by a future hardware adapter.

The generic restorer must still check all staged pages, reconstruct/hash the
logical whole original FLASH against the anchor, recheck UICR, stop radio/reset
sources and use the reviewed SRAM-only finalizer. Those consumers are pending.
The current exact-legacy gate and candidate 0.6.0 artifacts remain unchanged.

## Evidence

Independent Python fixtures use `struct` and `zlib.crc32`; their wire values do
not come from this encoder. OpenSSL EVP supplies the host callback backend and
Python hashlib independently checks family/full/table/page digests. No private
key or hardware is used.

Fresh verification on 2026-10-23:

- `work/ncs-venv/bin/python -m pytest -q tools/firmware/tests/test_loader_contract.py`:
  **93 passed**. The same 93 tests pass with compiler flags
  `-fsanitize=undefined -fno-sanitize-recover=all`.
- Complete corrected `tools/firmware/tests`: **562 passed, 39 subtests
  passed**, 53.16 s.
- Standalone Cortex-M4 Thumb `-Os` compile: **2383 bytes text, zero data/BSS**,
  no undefined symbols except `memcmp`, `memcpy`, `memmove`, `memset`.
  Largest measured local frame is 952 bytes for authorize; streaming hash uses
  320 bytes. Nested frames and adapter/crypto stack must still be budgeted.

The initial semantic stub run failed 56 tests; implementing the contract made
the cases pass. Additional tests exposed and corrected in-place table handling
and stale authority after invalid session reinitialization. Fault injection
covers every stream/table crypto step and selected code/anchor read boundaries;
negative and positive callback failures stay closed. Tests also cover fixed
spans, truncation, reserved bytes, partial commit, live identity/geometry/UICR,
typed-digest confusion, two-unit common family authorization, unknown loaders,
wrong tables/pages, all 256 page boundaries and reset/write-lock behavior.

ARM object/frame outputs are under `work/loader-contract-core-proof-v2/`. This is
not a linked production loader or proof that the final adapter fits reserved
flash. No CMake consumer, production signature or hardware operation was added.

Independent review found an alias bypass in eager output zeroing: an output
overlapping the live UICR expectation could erase that expectation before its
comparison and accept a mismatching zero-hash anchor. The original independent
reproducer now rejects both decode and authorization with `-EACCES`. Nine new
regressions cover that exact bypass, valid output overlap with source/records/
live data, and full/family digest output overlapping source bytes. All failed
against the eager-output code before the staging correction. The v1 proof is
preserved; v2 is the corrected source snapshot.
