# First installation with Android and the DK

This guide describes the implemented first-install source flow in the Android
app. The complete phone → DK → dimmer programming procedure still requires a
controlled physical qualification trial. No device was programmed while preparing
this guide. Passing source tests or seeing an nRF52840 identity is not that trial.

For a mounted dimmer already running custom firmware, use the separate
[device firmware update](android-bluetooth-trial.md).

The entry point is **Settings → Tools → First installation**. **DK tools** remains a
separate read-only monitor and backup tool; it does not start this procedure.

## What to prepare

- The Android app, an Android USB host adapter, and the DK's J-Link USB connection.
- One target in the project's validated SWD bench arrangement, isolated from
  household mains. Keep the established pin mapping and target supply arrangement;
  this guide does not introduce a different wiring scheme.
- One compatible Vomar common firmware ZIP. The original backup is saved privately
  on the phone. An additional export to Files or private cloud storage is optional.

The common firmware ZIP is shared across compatible devices. You do not prepare
an identity file, enter the IEEE address, or register each dimmer to flash it.
The app reads silicon identity directly. The original backup is specific to that
one device and must be kept privately.

## Choose firmware

Use **Choose firmware** for qualified releases, beta candidates and local packages.
The app detects the type; there is no separate qualification submenu. A local or
beta package needs explicit confirmation. Missing or invalid outer release and
first-install descriptor signatures are accepted only in this manual route.
ZIP bounds, canonical model/layout metadata, every component hash, protected
model/role tags, loader contracts and bootloader-compatible image signatures
remain checked. Incompatible or unrelated ZIP files are rejected.

Manual admission does not mark a package qualified or make it eligible for online
release selection, fleet updates or Zigbee OTA. A selected document and a saved
review are never execution approval.

## Operator sequence

1. Open **First installation → Choose firmware**. Review the warning for a local
   or beta package. Wait for the package checks. Changed bytes are rejected.
2. Tap **Read connected device**. Select the J-Link probe if more than one is
   present and grant Android's USB permission. This step reads live identity and
   memory geometry without halting, resetting or programming the target. Confirm
   the physical target is the intended dimmer: detecting an nRF52840 alone does
   not establish the commercial board model.
3. Tap **Backup**, then review **Capture original firmware?**.
   Watchdog preflight is automatic. An inactive watchdog is supported. An active
   watchdog is supported only when the signed release explicitly contains the
   `paused-reset-before-main-v1` handoff, the observed configuration pauses while
   the CPU is halted, and its bounded period and reload-channel configuration
   pass validation. Older releases without that signed capability still require
   an inactive watchdog. Unexpected or changing profiles stop the operation.
4. Confirming **Capture backup** temporarily halts the CPU and takes two complete
   copies of FLASH, FICR and UICR. It compares every byte before publishing an
   original archive. Capture does not reset the target, feed its watchdog, or
   erase/program FLASH or UICR. The stock images examined in this project start
   a watchdog with a nominal ten-second period and pause-on-halt configuration;
   the actual connected target is still checked, never assumed. See the
   [watchdog evidence and handoff scope](research-summary.md#inherited-stock-watchdog).
5. The app saves matching originals to an immutable private file and reopens it
   byte for byte. This verified handoff completes automatically; no file picker
   is required. Progress shows measured bytes across both complete reads.
6. Tap **Install firmware** and review the target. **Export backup copy** is
   optional. The app retains the exclusive USB connection across backup and
   review. It records each write intent durably, commits only after body checks,
   and verifies the complete image and unchanged UICR. Install progress counts
   actual original-read, programmed-page-readback and full-verification bytes.
   Before the first reviewed FLASH mutation, the app reads all eight volatile
   FLASH permission regions. If write protection is still active, it performs
   a reset with vector catch and confirms the CPU is halted at the reset state,
   original FICR/UICR and watchdog are unchanged, and FLASH permissions are clear.
   It does not write ACL or UICR registers. Original backup capture and a
   verification-only repair do not request this preparation reset. A region
   that prevents original readback stops installation before a reset or write.
   Saved reports include `programmingPreparation`, `installStep`, and
   `installAddress`; these report observed progress rather than granting access.

7. A successful write ends with the CPU **halted**. Tap **Start verified firmware**
   and confirm **Start firmware** as a separate action. The app reconnects to the
   same target, checks the unchanged watchdog profile, complete FLASH, FICR and
   UICR, then starts from the newly verified reset vector and releases debugger
   ownership. Pinned progress counts this complete image read. It never resumes
   the stock program counter into rewritten firmware.
   When the signed inherited-watchdog handoff applies, the new loader waits for
   one hardware watchdog reset before normal startup. The UI displays the
   observed nominal period (about ten seconds for the examined stock profile).
   This is a one-time first-install handoff, not a delay on ordinary updates and
   not a claim of measured phone-to-device timing.
8. An acknowledged start is not proof of correct buttons, lamp output, Bluetooth,
   Zigbee or stock restoration. Complete the separately agreed bench checks
   before treating the candidate as qualified. **Prepare another device** creates
   a new explicit session; it does not launch another installation.

Keep the phone, DK and target connected while an operation is active. The service
continues during screen changes and rotation, with a notification and Stop
action. Capture/install has a two-hour cancellation bound in the current source;
that bound is not a measured expected transfer time. Returning to the screen or
granting USB permission never authorizes capture or installation automatically.

## Cancellation and interrupted attempts

Use **Cancel operation**, **Cancel installation**, or the notification's **Stop**
action. Cancellation prevents subsequent operations; it cannot undo an erase or
programming operation already issued. Before any FLASH mutation, cleanup attempts
to restore the original CPU/debug intent. After a possible FLASH mutation it
retains the halt and does not request a CPU start. A disconnected probe or lost
acknowledgement can leave the actual CPU state uncertain; retain the report's
precise disposition rather than assuming cleanup succeeded.

After a failure, use **Save diagnostic report** and keep the original ZIP. A
process restart restores diagnostic evidence, never a USB lease, bench approval,
verified-start receipt or running operation. Do not delete app data or transaction
files to make a failed target look new. The retained journal blocks a fresh
capture of a target with prior possible programming, including a completed first
installation; partially rewritten firmware must not be labelled as its original
backup. **Prepare a different device** does not remove that protection.

## Explicit repair after an interrupted installation

Returning to the screen never restarts work. Use this sequence only for the same
retained attempt, target and common ZIP:

1. Choose the same release and tap **Read connected device**. The retained
   attempt is shown instead of allowing a new original capture.
2. New attempts reuse their verified private original automatically. For an
   older attempt with an external export receipt, **Choose existing original
   backup** selects that export or a byte-identical copy. Its bytes must match
   both the immutable private original and historical receipt. No new capture
   or manually maintained identity file is required.
3. Tap **Prepare repair preview** explicitly. This pauses the exact target,
   checks its identity and protected state, and validates the saved evidence. It
   does not erase or program FLASH. Repair progress reports actual validation,
   rebuilt-page readback and verification stages. A changed identity, release, original or
   journal head blocks the repair. The full FLASH scan takes place only after
   the separate repair confirmation, before any approved FLASH mutation; pages
   outside the previously issued mutation scope must still match the original.
4. Read the retained attempt and repair warning, then tap **Review and repair** and confirm **Continue
   repair**. Depending on actual contents, repair performs verification only,
   writes only a missing final commit, or rebuilds the bounded installation
   before committing last. Rebuilding discards custom settings created after
   first installation; the original private backup remains intact.
5. Successful repair again ends **halted**, requiring the separate **Start
   verified firmware** action. Each interrupted repair needs a fresh preview and
   confirmation. Restored screen state, a saved URI or an old review never grants
   permission to program or start the CPU.

The append-only repair journal retains the greatest issued mutation scope across
all attempts. A verification-only pass cannot expand it. Initial export and
repair evidence are durably recorded before target mutations. An acknowledged
start suppresses this initial-install repair route: it is not an ordinary
firmware updater or factory-reset shortcut. If original evidence is unavailable,
keep the report and stop; this flow does not offer mass erase, `recover`, UICR
programming or deletion of journals as a repair method.

## Keep one private original archive per device

The original ZIP contains full `flash.bin`, `ficr.bin` and `uicr.bin`, a manifest,
and its explanatory README. Its metadata records the two equal acquisitions,
actual halted-acquisition scope and hashes. The app also retains an immutable private
copy and transaction evidence. A backup is not proof that restoration has been
physically tested.

Keep the exported original ZIP intact in private storage. It can contain the
device's identity and network information; it does not belong in a public GitHub
release. There is no separate user-maintained UID/MAC registry to preserve. The
shared release ZIP, per-device original ZIP and optional diagnostic report serve
different purposes.

## Saved originals and restoration

Verified private originals are associated with **Devices** by their hardware UID.
Existing names, rooms and transport mappings are preserved; a newly backed-up
UID receives an organisational record without an invented firmware version.
Open **Devices → device → Original firmware** to export a copy or explicitly
restore its original FLASH with the DK. The connected UID, geometry, FICR and
UICR must match the backup. Restore writes FLASH pages with durable intents and
exact readback, restores the vector page last, and verifies the full original.
It never writes UICR. It ends halted; disconnect the DK and power-cycle the dimmer
only after successful verification. An interruption needs a new explicit review.

Private originals survive app upgrades. Clearing app data or uninstalling the
app deletes them: retain an exported copy. **First installation help** contains
the explanation and diagnostic export. Software/fake-target checks do not qualify
this physical restoration procedure.

## Progress, remaining time and USB speed

Android 1.0.7 shows the current phase above a second, teal overall progress bar.
The overall bar covers the active reviewed installation or repair through its
final verification. A two-pass backup and the separately reviewed start have
their own overall totals. Waiting for a review is not a timed transfer.

The overall value uses completed bytes/pages with relative phase weights; it
stays increasing across phase boundaries and advances when verified work can be
skipped. The remaining time is approximate, learned from observed progress and
a monotonic clock. It displays **Estimating remaining time…** until there are
sufficient samples, after a phase change or when progress samples are stale.
It is not a deadline or evidence of hardware qualification.

The programming path uses 1MHz SWD, bounded queued accesses and the same open
USB handle. Each queued FLASH write is acknowledged and READY is checked before
the next word; uncertain writes are never replayed automatically. Presence
checks against Android's USB service are limited to one per 250ms, while owner,
closed-handle and transfer-error checks remain per I/O. UID, halted CPU and
watchdog checks surround bounded batches/pages. Original comparisons, ACL
preparation, unchanged-UICR checks, durable intent and complete final readback
remain required. A link/identity error prevents programming; no unlock fallback
or automatic start is introduced.

Repair reuses pages already proven correct within its issued frontier and any
correct tail beyond the last required reconstruction. It preserves contiguous
mutation intent for intervening unissued pages. A verified image uses the final
complete comparison/hash pass without an extra redundant verification pass.

Synthetic operation-count regressions measure the transport improvement;
physical phone/DK throughput remains separately qualified. Keep USB and power
connected during an active repair. An APK upgrade must wait until the owned
operation has ended and its original/journal have been retained.
