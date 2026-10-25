Source integration pending independent review of the isolated core.

- SAME canonical `:core` source module includes src after review; no copies.
- Persist immutable initial OriginalExportReceipt immediately after successful
  same-URI export/reopen and binding derivation, before installation admission.
- Private start markers are binding-specific: intent durable before explicit
  start; acknowledged marker suppresses routine interrupted-install offer.
- Resume option discovery reads exact same-UID retained base record, protected
  original, receipt, and complete hash-linked resume journal. Missing/corrupt or
  multiple progressed bindings is blocked, never silently skipped.
- User-selected cloud copy is reopened read-only and byte-exact compared to the
  protected original and initial receipt. No replacement/re-export/recapture.
- Explicit prepare holds USB token, validates current signed source, constructs
  generation-bound ReviewedResume, and allows only its ResumeHardwareAuthority
  to restore known NVMC CONFIG1/2 to READONLY AFTER HALT/READY and exact FICR/UICR.
- Separate final dialog correlates request/binding/release/head and calls engine.
- Every resume failure/cancel keeps inherited HALT uncertainty, even zero new
  writes. No catch path restores original CPU control from partial firmware.
- Successful complete image still requires separate receipt-gated explicit
  reset-and-start and signed inherited-watchdog policy; never release old PC.
- Repair UI warns rebuilding can reset current custom settings. Only complete
  current read determines rebuild/commit-only/verify-only mode.
