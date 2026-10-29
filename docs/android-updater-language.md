# Android interface language

Use this reference when changing Android strings or progress messages. For the
owner's workflow, see [Android updater](android-updater.md). English is the
source language. Preserve user-entered device names, rooms and broker labels.

## Words and observable meaning

| Term | Meaning |
| --- | --- |
| Dimmer | The physical target checked through live identity; a saved label is not identity proof. |
| Firmware ZIP | The signed package selected for an operation. Distribution and native firmware versions are distinct. |
| Bluetooth recovery | The independent maintenance application; normal Zigbee operation does not imply a live BLE connection. |
| Check / inspect | Read-only work; never imply that a check installs or starts firmware. |
| Resume / repair | A new reviewed operation using retained evidence; never reuse previous consent. |
| Stop | Stop subsequent requests and retain progress. A remote request, internal copy or reset may already have started. |
| Verified firmware | Matching authenticated image evidence; not measured lamp operation. |
| Online result | An operator-observed result, separate from transfer verification and restart acknowledgement. |
| Original backup | The retained device-bound stock capture; a new capture cannot replace it during repair. |
| Experimental | Firmware with explicitly unverified qualification; a published application release does not remove that status. |

## Message rules

Lead with the operation, result and next useful action. Keep enum names, hashes
and protocol detail in technical details unless needed for a decision. Show
identity and target version in mutation review. A changed target or package
invalidates the displayed action and requires a fresh review.

Distinguish transferred bytes, authenticated image verification, restart request,
restart acknowledgement and observed return. A missing acknowledgement means
uncertainty, not proof of failure. Explain retained progress and the next safe
inspection instead of inviting an unconditional retry.

Bluetooth permission or pairing success does not start an operation. Describe a
previous check as historical. Do not invent a wrong PIN, weak signal or defective
dimmer as the cause of an unknown error. Preserve entered values after failure.

For originals, say whether the copy is private or external. The required Android
save/reopen happens privately after capture. External export is optional in that
screen but essential before uninstalling or clearing app data. Never say all
backups survive ordinary Android uninstall.

## Source and verification

UI text belongs in `apps/android-updater/app/src/main/res/values/strings.xml`
where practical; `UpdateCopy` isolates runtime wording from operation authority.
Check changes against `UiPolicy`, `SessionPresentation`, the relevant Activity
and its service/controller. Exercise enabled, denied, interrupted and uncertain
states with synthetic fixtures. Check actual renders at large text sizes and in
both themes; emulator copy tests do not qualify physical Bluetooth or USB.
