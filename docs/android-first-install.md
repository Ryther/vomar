# First installation with Android and the DK

First installation replaces firmware on an isolated bench target. It is separate
from [updating an already-custom dimmer](android-bluetooth-trial.md). The complete
phone → DK → dimmer procedure still needs its own physical qualification; this
guide and software tests do not provide that qualification or operator approval.

Open **Settings → Tools → First installation**. **DK tools** is a separate
read-only monitor/backup tool and never starts this procedure.

## What to prepare

- An Android phone with Vomar, USB host adapter and the DK's J-Link connection.
- The intended target in the established SWD bench arrangement, **isolated from
  household mains**, with wiring and target supply checked by the operator.
- One complete compatible common firmware ZIP; do not extract its images.
- Independent private storage for each device's original backup.

The firmware ZIP is shared across compatible targets. An original ZIP is specific
to one physical device. No manually maintained UID/IEEE/MAC registry is required;
the app reads live identity. Detecting an nRF52840 alone does not prove the board
is the intended commercial model.

## Choose firmware

Use **Choose firmware** for a qualified release or an explicitly reviewed
beta/local package. The app detects the type and shows the relevant warning.
Only this manual route can admit missing outer signatures; image signatures,
hashes, model/layout, roles and loader compatibility remain mandatory. A local
package cannot grant a watchdog capability without its required signature.

Selecting a package starts no device work and does not qualify it for catalog,
fleet or Zigbee OTA use.

## Operator sequence

1. **Choose firmware.** Review the exact package and any beta/local warning.
2. **Read connected device.** Choose the intended J-Link probe if necessary and
   grant Android USB permission. This reads identity and geometry without
   halting, resetting or programming the target. Check the physical target.
3. **Backup.** Review **Capture original firmware?**. The app checks the live
   watchdog profile. An active watchdog is admitted only by the signed bounded
   `paused-reset-before-main-v1` capability and a verified pause-on-halt profile;
   otherwise capture stops. Do not bypass that refusal.
4. Confirm **Capture backup**. The app temporarily halts the CPU and reads
   FLASH/FICR/UICR twice, comparing every byte. It does not erase/program them,
   reset the target or feed the watchdog. It retains the exclusive connection.
5. The matching original is saved to an immutable private archive and reopened
   byte for byte. This handoff completes without an external file picker.
   **Export backup copy** provides an independent copy; keep it permanently
   before uninstalling or clearing app data.
6. **Install firmware.** Review and confirm the exact target. The app records
   intent before bounded FLASH writes, commits last, and checks the complete
   image and unchanged UICR. If supported, a necessary reset/vector-catch step
   prepares volatile FLASH permissions while retaining HALT; it never writes
   ACL/UICR registers. Backup capture and verify-only repair do not request
   that preparation reset.
7. Successful installation ends **halted**. **Start verified firmware** needs a
   separate **Start firmware** confirmation. The app rechecks identity,
   complete FLASH/FICR/UICR and the watchdog before starting from the verified
   reset vector. The signed inherited-watchdog handoff may wait for one genuine
   watchdog reset before ordinary boot; it is not a delay added to normal updates.
8. Observe the resulting buttons, lamp, Bluetooth and Zigbee separately. An
   acknowledged start does not establish those functions or stock restoration.

Keep phone, DK and target connected while an operation is active. A foreground
notification retains progress across screen changes and provides Stop. Opening
a screen, granting USB permission or preparing another device does not approve
another capture or installation.

## Cancellation and interrupted attempts

Use the visible Cancel/Stop action. It prevents subsequent requests but cannot
undo a write already issued. Before possible FLASH mutation, cleanup attempts to
restore original CPU/debug intent. After possible mutation it retains HALT and
requests no start. A lost connection or acknowledgment can leave state uncertain;
keep the precise reported disposition.

Save the diagnostic report and original ZIP. Restart restores records, never a
USB lease, review or running operation. Do not delete journals or capture partially
modified FLASH as a replacement original. A retained transaction can block a new
capture even after a completed first installation; **Prepare a different device**
does not remove that protection.

An older Android 1.0.7 reader can fail with **Syntax error in regexp pattern**.
After the active operation ends, upgrade over the existing app with the same
signer. Preserve originals/journals; the error alone does not establish CPU or
FLASH state. An uncertain start still needs explicit repair and a separate start.

## Explicit repair after an interrupted installation

Use the same retained attempt, target and common ZIP:

1. Choose the same firmware and **Read connected device**. The retained attempt
   appears instead of allowing a replacement original capture.
2. Reuse the private verified original. If an older attempt requires its external
   receipt, **Choose existing original backup** accepts that export or a
   byte-identical copy. Changed bytes are rejected.
3. **Prepare repair preview** pauses and checks the target and retained evidence;
   it does not erase/program FLASH. A changed identity, release, original or
   journal head blocks repair.
4. Read the retained attempt, choose **Review and repair**, then confirm
   **Continue repair**. Only after that review does the full scan check that
   never-issued pages still match the original. Repair may verify only, write a
   missing final commit, or rebuild the bounded image. A rebuild discards custom
   settings created after first installation, while retaining the original.
5. Successful repair ends halted. **Start verified firmware** is a separate
   reviewed action; another interruption needs a new preview and review.

Missing originals, corrupt journals or unknown bytes block this route. An
acknowledged start suppresses initial-install repair; it is not a factory-reset
shortcut or the ordinary updater. This procedure does not offer mass erase,
`recover`, UICR programming or journal deletion as repair.

## Keep one private original archive per device

The original ZIP contains `flash.bin`, `ficr.bin`, `uicr.bin`, a manifest and
README. Its hashes and metadata describe the actual acquisition. Keep it intact
and private: it may contain device identity and network information. A successful
backup does not prove restoration has been physically qualified.

An original, a shared firmware release and a diagnostic report have different
purposes. Exporting an original does not export all app state or credentials.

## Saved originals and restoration

Devices associates a private original with its hardware UID. Use
**Devices → device → Original firmware** to export a copy or review explicit
original restoration with the DK. Live identity, geometry, FICR and UICR must
match. Restoration records bounded FLASH intent/readback, restores the vector
page last, verifies the original and ends halted. It never writes UICR. Only
following successful verification should the operator follow the stated
probe-disconnection/power-cycle instructions. An interruption needs fresh review.

App upgrades preserve private originals. **Uninstall/Clear storage deletes them**;
keep the independent export. Physical restoration remains separately unqualified.

## Progress, remaining time and USB speed

The current phase and overall progress have separate bars. Remaining time is an
estimate learned from verified progress, not a deadline. **Estimating remaining
time…** is expected before enough samples or after a phase change. Backup and
separately reviewed start have their own totals.

Do not disconnect USB/power to force progress. Keep the original, package and
journal after failure. Wait for an owned operation to end before an APK upgrade.
Implementation/performance details belong in [development](development.md) and
[the first-install contract](../tools/android/first_install_contract/README.md).
