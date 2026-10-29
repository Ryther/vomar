# Android explicit repair integration contract

`apps/android-updater/core/build.gradle.kts` includes the canonical portable
first-install and resume sources directly. Android app adapters implement private
persistence, document access, exclusive USB ownership and reviewed presentation.
These are current integration requirements, not automatic recovery permission.

1. Persist the immutable `OriginalExportReceipt` after successful exact-document
   save/reopen and binding derivation, before installation admission. Android's
   initial save/reopen can be private; the document identifier is not necessarily
   a cloud URI.
2. Discover repair only from the exact same-UID retained record, protected original,
   initial receipt and complete hash-linked journal. Missing/corrupt or multiple
   progressed bindings block admission. Do not silently skip them or recapture.
3. Reopen the selected original read-only and compare complete bytes with the
   protected original and receipt. No replacement export or new capture can
   authorize repair.
4. Explicit preparation holds the USB token, validates the signed source and
   constructs generation-bound `ReviewedResume`. Only its
   `ResumeHardwareAuthority` may restore known NVMC CONFIG1/2 to READONLY, after
   HALT/READY and exact FICR/UICR checks.
5. A separate final review correlates request, binding, release and journal head.
   Full current readback determines REBUILD, COMMIT_ONLY or VERIFY_ONLY. Warn
   that rebuilding may reset current custom settings.
6. Every failure/cancel preserves inherited HALT and mutation uncertainty, even
   with zero new writes. Never restore old CPU control from partial firmware.
7. Verified completion still requires separate receipt-gated reset-and-start
   and the signed inherited-watchdog policy. Persist start intent before the
   request; acknowledgement suppresses the routine interrupted-install offer,
   while an uncertain result requires reconciliation.

Keep original/receipt/journal material private. Android uninstall and app-data
clearing delete it; externally export originals before either action. See
[the engine reference](../../first_install_contract/README.md) and
[operator workflow](../../../../docs/android-first-install.md).
