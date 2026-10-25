# Portable first-install contract candidate

Source-only Kotlin engine under `org.openvimar.installer`; not wired into the
Android APK, a physical SWD driver, release UI or deployable firmware set.
The approved scope is Phase4 of
`docs/superpowers/plans/2026-10-23-common-first-flash-loader.md`.

Data flow is deliberately explicit:

1. Validate the bounded original Android five-entry backup ZIP. A single export
   cannot independently prove the producer's two acquisition passes or identify
   the commercial board.
2. Require an explicit successful document export, reopen that exact document,
   validate it independently and compare the complete ZIP bytes. Only this
   capability permits deriving the page table and original-bound VAR1 anchor.
3. Authenticate one schema3 common ZIP, its manifest and its static public
   `first-install.json`/`.sig` entries using the trusted public P256 key.
   Descriptor/component duplicates must agree. `loader.bin` is exactly48KiB
   with an all-FF anchor placeholder; its typed family measures code44KiB.
   Legacy48KiB and unknown types never alias. There is no second user download.
4. Create an immutable plan: common loader code + original-bound anchor + signed
   MAIN/RECOVERY, with erased gaps/storage for a fresh network installation.
5. Acquire a separately owner-authorized, exclusive, quiescent SWD session for
   the exact plan/UID. Match live original FLASH/FICR/UICR before mutation.
   Recheck full identity/UICR before each page transaction. Before each bounded
   mutation, check cancellation and the non-reconnectable target/lease identity.
   Recheck UID after each page; full UICR again before commit and final success.
6. Journal intent before each bounded FLASH page erase/word write. Read back
   body with commit erased; verify complete body; write the four-byte anchor
   commit last; verify complete FLASH, identity and unchanged UICR afterward.

The adapter API intentionally has no recover, mass erase, UICR write, halt or
reset method. Its future implementation must establish owner-authorized,
CPU-halted exclusive/quiescent
ownership separately, reject physical target/connection changes, and never add
implicit destructive fallback. The engine cannot attest an arbitrary adapter.

An interruption is not an atomic installation. Original export and journal are
retained. Explicit resume is unsupported in this first source phase: an existing
journal cannot silently authorize a retry against arbitrary mixed FLASH. A
failure around the final commit retains commit-uncertain evidence.

The public first-install descriptor is a versioned source contract embedded in
the same schema3 common release ZIP;
it does not make existing schema2 APK/runtime consumers support the upcoming
schema3 typed loader records. Integration needs an independently reviewed
matched executable set and separately approved physical qualification.

Implementation plan (inline, root-approved):

- [x] RED/GREEN standalone compiler harness and independent Python fixtures.
- [x] Strict original ZIP/export capability and immutable anchor/table codec.
- [x] Public-key common artifact authority, reusing unchanged core image parser.
- [x] Journalled abstract SWD engine and stateful failure/cancellation tests.
- [x] C-authoritative anchor encode/decode/table/family interop and proof.
- [ ] Independent review before integration.

The isolated harness compiles the unchanged existing portable core sources
alongside this island into a temporary JVM module; this reuses its internal
`PackageValidator.validateImage` without changing the core/API/Gradle or using
reflection. Future integration belongs inside the reviewed core module.

Run the isolated tests from the repository root:

```sh
work/ncs-venv/bin/python -m pytest -q tools/android/first_install_contract/tests
```

The harness uses the existing cached Kotlin compiler and dependencies, with no
Gradle or network invocation. It compiles the authoritative unchanged C anchor
codec with undefined-behavior sanitization. Independent Python fixtures,
the actual Kotlin backup archive producer, and the independent schema3 Python
producer's public synthetic ONE-ZIP fixture cross the Kotlin/C boundary.
Synthetic qualification claims in fixtures are test data only.

The stateful target model enforces NOR programming and the erased commit until
the final four-byte write. A boundary sweep injects 572 failures, covering every
page erase, program operation and journal publication in the synthetic install,
plus selected acquisition, close, identity and read boundaries. No target
mutation follows an injected failure. Separate tests exercise cancellation,
transport generation/UID changes, mismatched originals, readback corruption,
lost commit acknowledgements and persistence acknowledgements.

One synthetic successful transaction uses 256 page erases, 20 bounded programs,
1,024 FLASH page reads and 261 UICR reads. The program count depends on artifact
contents; the page/identity guards do not hash UICR for every word.

`FileInstallJournal` is a host-filesystem implementation with exclusive initial
creation, forced file/directory writes and atomic replacement. It preserves
existing/incomplete records and monotonic uncertainty flags. Its Linux/JVM
tests establish that contract here; this is not an Android SAF journal adapter.
The export port likewise requires a future actual document implementation.
Neither interface supplies physical I/O or qualifies a first installation.

See `analysis/app/first-install-engine-2026-10-23.md` and
`work/first-install-contract-proof-v2/proof-manifest.json` for the frozen source
pins and verification commands.
