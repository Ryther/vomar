# Shared first-install contract

The Kotlin engine in `src/` is compiled directly into the Android `:core` module
by `apps/android-updater/core/build.gradle.kts`. Android Activities, services and
USB adapters live in `apps/android-updater/app/`; the portable core supplies
archive, signed-package, plan and transaction authority. This is implemented
source, with separate physical qualification. For operator steps use
[Android first installation](../../../docs/android-first-install.md).

## Authority flow

1. Validate a bounded original backup ZIP, its exact entries, metadata, geometry
   and hashes. A ZIP cannot independently prove how its producer acquired two
   copies or identify a commercial board; capture provenance and live identity
   remain separate requirements.
2. Save and reopen the complete exact archive through `ArchiveExport`, validate
   the reopened bytes independently and compare the entire ZIP. Only the resulting
   capability permits deriving the original page table and VAR1 anchor.
3. Authenticate the signed schema3 common ZIP and embedded
   `first-install.json`/`.sig` with the trusted public P-256 key. Descriptor and
   component duplicates must agree. `loader.bin` is exactly 48 KiB with an erased
   anchor placeholder; its typed family measures precisely 44 KiB of code.
4. Construct an immutable original-bound plan: loader, anchor, signed MAIN and
   RECOVERY, with erased gaps/storage for fresh network installation.
5. Acquire separately authorized exclusive, halted, quiescent SWD ownership.
   Match live original FLASH/FICR/UICR. Recheck identity/UICR before bounded page
   transactions and UID after each page; cancellation or lease change stops work.
6. Persist intent before erase/program, verify the complete body with commit
   erased, write the four-byte anchor commit last, then verify complete FLASH,
   identity and unchanged UICR. Completion leaves the target halted.

The engine's adapter has no recover, mass-erase, UICR-write or reset operation.
The platform adapter owns reviewed HALT and the separate verified start. A
signature or selected ZIP is never sufficient write consent. The signed
`paused-reset-before-main-v1` policy supports only the admitted inherited
watchdog profile; capture does not feed or reset that watchdog.

## Android persistence and interruption

`InitialInstallService` automatically invokes
`active.export(persistence.privateExport(...))` after two-pass capture. The
required save/reopen therefore occurs in private app storage. External document
export is an additional user-selected copy; it is essential before uninstall or
app-data clearing, which deletes private originals/journals/credentials. Android
automatic backup is disabled. Desktop has an explicit export/reopen journey.

`FirstInstallEngine` plans are single-attempt. An existing transaction blocks
ordinary replay. The separate `first_install_resume_contract` supports explicit
repair only with the exact retained original, immutable initial receipt,
hash-linked journal, fresh signed plan and new review. It cannot recapture mixed
FLASH as a replacement original. Failure around commit remains uncertain; no
catch path resumes the old CPU into partial firmware. Successful installation
requires a separate receipt-gated start. See the
[resume integration contract](../first_install_resume_contract/android/integration-contract.md).

## Verify changes

Run focused portable tests in the pinned development environment:

```sh
python -m pytest tools/android/first_install_contract/tests
```

The isolated harness uses cached Kotlin dependencies and independent synthetic
Python fixtures, plus the authoritative C anchor codec with undefined-behavior
sanitization. Stateful models exercise NOR programming, journal boundaries,
cancellation, generation/UID changes, original mismatches, readback corruption
and lost commit acknowledgements. `FileInstallJournal` supplies host filesystem
persistence, not a substitute for Android adapter checks.

Also run the affected core/app tests and synthetic instrumentation using the
[development guide](../../../docs/development.md). Host/JVM/emulator checks do
not qualify a real phone, USB probe, watchdog handoff, power stage or power cut.
Never use stock captures or household targets as automated fixtures.

## Historical isolated-engine evidence (2026-10-23)

The source-phase boundary sweep injected 572 failures around page erase, program,
journal publication and selected identity/read/ownership boundaries. No target
mutation followed an injected failure. One synthetic successful transaction
used 256 erases, 20 bounded program calls, 1024 FLASH-page reads and 261 UICR
reads. Program count depended on synthetic content; the guards did not hash
UICR per word. These are historical model observations, not real USB/FLASH
timing, current-suite counts or physical qualification. Later Android integration
and explicit resume supersede that phase's original “not wired” limitation.
