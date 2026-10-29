# Android presentation and operation boundaries

This reference is for Android contributors. Use [the updater guide](android-updater.md)
for owner tasks and [interface language](android-updater-language.md) for copy.
The top-level destinations are Devices, Activity and Settings; advanced device
operations retain their own reviewed flows.

## Derive presentation from owned state

`SessionController.presentation` publishes immutable `SessionPresentation` facts.
`inspect()` reads the selected package, checkpoint and report without creating a
transport or saving a checkpoint. Lifecycle inspection must not overwrite an
active operation's progress. `UiPolicy` derives visible actions from those facts,
permissions and service attachment. Controller admission remains authoritative.

| State | Required presentation |
| --- | --- |
| No valid package | Offer import; keep an existing report exportable. |
| Bluetooth permission missing | Offer permission; granting it does not start scanning or mutation. |
| Valid package, idle | Offer the supported check or reviewed update. |
| Partial session | Offer inspection and explicit resume using retained evidence. |
| Busy | Retain target, status and Stop; reject concurrent ownership. |
| Image verified | Distinguish verification from restart and operator-observed return. |
| Restart uncertain | Preserve uncertainty; a fresh bounded review is required. |
| Retained first installation | Inspect the exact original, receipt and journal before offering repair or start. |

## Bind every action to what was reviewed

Before a session action, `freshActions()` compares the rendered package summary
with the service's current summary. A changed device updates the screen and asks
for a new action. It cannot turn a stale button into consent for another target.

An imported document URI stays pending until controller admission. The started
service retains import ownership, and binder admission is synchronous. Existing
atomic package validation/persistence still applies. Check report availability
independently: a missing or corrupt ZIP must not make an existing diagnostic
report inaccessible or enable a device operation.

First installation uses `InitialInstallService` and the shared Kotlin contract.
After two-pass capture, the service calls `active.export(persistence.privateExport(...))`;
this performs required archive save/reopen privately. An external export is an
additional copy, not the sole installation admission step. Preserve originals,
receipts and journals on interruption. Android uninstall and app-data clearing
delete them, so the UI must explain external export before those actions.
Verified FLASH remains halted until a separately reviewed start.

## Keep the active task usable

Keep the selected identity and operation visible while the body scrolls. Bound
long labels visually while exposing their full accessible name. Use native
headings, focus/ripple behavior, dp spacing, sp text and at least 48 dp touch
targets. Respect system insets and large fonts in both themes and landscape.

Use one primary action for the current step, with optional technical details.
Announce meaningful state changes through a polite live region without reading
every upload percentage. Only current acknowledged transfer progress drives a
determinate bar. Stop must remain available during long checks and operations.
Preserve errors and entered values when a local export or preparation finishes.

## Source and evidence

Owners are `apps/android-updater/app/src/main/kotlin/org/openvimar/updater/`
(`MainActivity`, `UiPolicy`, `UpdateCopy`, installer Activities/services) and
`apps/android-updater/core/`. The core directly includes portable first-install
and resume contract sources; see their [contract reference](../tools/android/first_install_contract/README.md).

Run the matching JVM and synthetic instrumentation suites through the pinned
[development environment](development.md). `CiUiSuite` groups the required
instrumentation classes; verification must find executed, non-skipped cases
from every expected class. Retain exact-candidate renders for long names,
large fonts, dark/light themes, denied review, Stop and interrupted repair.
Historical UI test counts do not establish current coverage. Physical pairing,
USB permissions, TalkBack listening and device operation require separate checks.
