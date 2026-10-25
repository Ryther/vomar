# First installation with Android and the DK

This guide describes the implemented first-install source flow in the Android
app. The complete phone → DK → dimmer programming procedure still requires a
controlled physical qualification trial. No device was programmed while preparing
this guide. Passing source tests or seeing an nRF52840 identity is not that trial.

For a mounted dimmer already running custom firmware, use the separate
[Bluetooth trial update](android-bluetooth-trial.md).

The entry point is **Settings → Tools → First installation**. **DK tools** remains a
separate read-only monitor and backup tool; it does not start this procedure.

## What to prepare

- The Android app, an Android USB host adapter, and the DK's J-Link USB connection.
- One target in the project's validated SWD bench arrangement, isolated from
  household mains. Keep the established pin mapping and target supply arrangement;
  this guide does not introduce a different wiring scheme.
- One signed common firmware ZIP and a destination for the original backup that
  Android can both write and reopen. A local Files destination can be used before
  copying the completed original ZIP to private cloud storage.

The common firmware ZIP is shared across compatible devices. You do not prepare
an identity file, enter the IEEE address, or register each dimmer to flash it.
The app reads silicon identity directly. The original backup is specific to that
one device and must be kept privately.

## Choose the correct package route

| App action | Accepted package | Purpose |
| --- | --- | --- |
| **Choose common release** | A signed, qualified common release | Ordinary installation once its release checks have passed. |
| **Qualification options → Bench qualification → Choose candidate** | A signed qualification candidate | One explicitly reviewed bench trial while physical release checks are pending. |

Firmware 1.0.0 and the earlier local 0.6.x candidates are marked `qualification-candidate`; their thirteen
physical qualification flags remain false. Its signature proves the approved
package contents, not successful device tests. It must use the separate bench
route. The normal release validator and fleet updater reject it. Selecting a
candidate grants no installation approval by itself.

## Operator sequence

1. Open **First installation** and choose the common release, or deliberately use
   the bench qualification route. Wait until the app has checked the ZIP,
   signature and components. A package that changes when reopened is rejected.
2. Tap **Choose DK and read target**. Select the J-Link probe if more than one is
   present and grant Android's USB permission. This step reads live identity and
   memory geometry without halting, resetting or programming the target. Confirm
   the physical target is the intended dimmer: detecting an nRF52840 alone does
   not establish the commercial board model.
3. Tap **Capture original backup**, then review **Capture original firmware?**.
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
5. When **Save original backup** appears, choose a new file destination and wait.
   The app writes the verified original ZIP, reopens that same selected document,
   and checks its complete contents. Cancelling the picker grants no installation
   approval. A provider that cannot reopen the saved file cannot complete this
   gate; choose another destination.
6. When **Review and install** appears, check the target UID, original-backup
   digest and release digest shown for the held transaction. Confirm **Install
   firmware** only for that target. The app retains the exclusive USB connection
   across capture, export and this review. It programs with durable transaction
   records, writes the final anchor commit only after body checks, and verifies
   the complete installed FLASH and unchanged original UICR.
7. A successful write ends with the CPU **halted**. Tap **Start verified firmware**
   and confirm **Start firmware** as a separate action. The app reconnects to the
   same target, checks the unchanged watchdog profile, complete FLASH, FICR and
   UICR, then starts from the newly verified reset vector and releases debugger
   ownership. It never resumes the stock program counter into rewritten firmware.
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
retained attempt, target and signed common ZIP:

1. Choose the same release and tap **Choose DK and read target**. The retained
   attempt is shown instead of allowing a new original capture.
2. Tap **Choose existing original backup**. Select the original exported ZIP.
   A byte-identical copy moved to another Files or cloud location is allowed:
   its bytes must match both the immutable private original and the historical
   successful export receipt. No second backup or manually maintained identity
   file is required. Selecting a document starts no target operation.
3. Tap **Prepare repair preview** explicitly. This pauses the exact target,
   checks its identity and protected state, and validates the saved evidence. It
   does not erase or program FLASH. A changed identity, release, original or
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
