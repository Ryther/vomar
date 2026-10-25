# Android updater guided interface

Historical interface notes for apps 0.1.4/0.1.5. For the current 1.0.3 interface
and qualification scope, see [the updater guide](android-updater.md).

App 0.1.4 implements the four priorities from the Android 0.1.3 critique:
state-dependent actions, an always-visible device identity, a clearer task
hierarchy and native accessibility. The scope is the Android app; firmware,
signed device packages and reset authorization are unchanged.

## Presentation and authority

`SessionController.presentation` publishes immutable `SessionPresentation`
facts. `inspect()` reads the selected package, checkpoint and report without
creating a transport or saving a checkpoint. A lifecycle inspection cannot
replace an active operation's progress message.

`UiPolicy` derives available controls from those facts, current Android
permissions and service attachment. It does not grant command authority.
The existing controller admission, generation, identity, verified-image and
uncertain-reset checks still apply to every operation.

| State | Main action | Supporting actions |
| --- | --- | --- |
| Loading session | Wait | No device commands |
| Empty or unreadable package | Import package | Export existing report when available |
| Bluetooth permissions missing | Allow Bluetooth | Change package and technical details |
| Valid package, no checkpoint | Start update | Optional read-only Bluetooth check |
| Previous partial update | Resume | Optional read-only check |
| Active import, check or update | Wait for operation | Stop subsequent requests |
| Final firmware verified | Record online result | Record offline; verify uncertain restart explicitly |
| Online confirmed manually | Export report | Correct an accidental online confirmation |
| Offline after restart request | Record corrected result | Read-only Bluetooth diagnosis; request permissions if necessary |

Granting permissions never starts an update, probe or reset automatically.
Historical successful Bluetooth verification is labelled as a previous check,
not a live connection. A newly admitted command clears old progress; only real
update progress drives the determinate bar and suppresses repeated spoken
percentage announcements.

## Device and file binding

The pinned header shows the selected device name, target firmware version and
verification evidence. Long names are bounded in the pinned header, with full
text available to accessibility services, the native tooltip and technical
details. The main content scrolls independently.

Before a main or secondary device/report action, `freshActions()` compares the
rendered package summary with the service's current summary. A changed device
updates the screen and requests a new explicit action. It does not act on the
new device through a stale button.

An imported document URI remains pending until the existing controller admits
the import. A started service retains the import host; the binder returns
admission synchronously instead of racing a second queued import intent against
inspection. Package bytes and selection still use the existing verification
and atomic persistence path.

Report availability is checked independently of package readability. A valid
session pointer and existing report remain exportable when the ZIP is missing
or invalid; no update or device check is enabled from that incomplete state.

## Layout and accessibility

- One filled primary action; secondary actions use native text/ripple controls.
- Current step replaces the former list of all phases. Connection help and
  technical/file options expand on request.
- Spacing uses dp and text uses sp. Controls have at least 48 dp height and
  8 dp between adjacent targets.
- Device and step headings use AndroidX accessibility heading semantics,
  including compatibility support for older API levels.
- Important state changes use a polite live region; upload percentages remain
  available without announcing every acknowledged chunk.
- System bars and content respect insets. Light and dark semantic color roles
  provide explicit contrasting text, controls and system-bar icons.
- Body width is bounded on wider windows; landscape uses a shorter pinned
  device label and retains scrollable actions at large font scales.

AndroidX Core 1.12.0 was already present at runtime; it is now explicitly
declared for its compatibility API. Dependency verification and locking remain
enabled. The app continues to use Kotlin and Android Views with no web surface.

## Verification boundaries

Unit coverage includes read-only inspection, partial/verified checkpoints,
foreign identities, missing/corrupt packages with an existing report, historical
probe binding, operation admission, progress reset and permission/result paths.
Instrumentation covers premature controls, restoration, heading semantics,
touch targets, pinned identity, stale secondary actions, manual result
correction, read-only checks and the existing stale reset confirmation.

Fresh render and test artifacts are under `work/android-ui014/`; the signed APK
and audit are under `experiments/android-updater/20261023-guided-014/`. Early
emulator System UI ANR captures are diagnostic failures, not visual acceptance
evidence. Use the later normal/large/night/landscape captures.

Emulator evidence is API35 with simulated BLE. Manual TalkBack listening,
physical Android 16 pairing and real radio performance are not established by
these UI checks. Existing device-specific firmware ZIPs remain unchanged.

Final evidence: 43 core JVM and 100 app JVM tests, 41 Python tests, a 16-test
functional emulator suite before the final progress refinement, followed by
11 targeted final-source render/state checks (normal, 200%, dark and landscape)
and two additional long-name/system-bar checks. Release lint, strict dependency
verification, signature and APK-content audit passed. Native compositor-idle
captures replace transient frames from early emulator boot. No physical dimmer
was programmed or connected by these tests.

## 0.1.5 polish

The guided structure and action policy are preserved. Connection help, extra
options and technical/file utilities now share a quieter, start-aligned 14 sp
role while retaining 48 dp touch targets and native ripple/focus behavior.
Enabled and disabled text use explicit semantic color states in both themes;
disabled text contrast is at least 4.8:1 against its applicable backgrounds.
Disclosure controls expose their expanded/collapsed state to accessibility
services through AndroidX compatibility APIs.

Local export, outcome saving and resume preparation have specific loading
titles. During these short local operations, a previous result/error message
is temporarily hidden; it becomes visible again when the operation finishes.
The uncertain-reset dialog identifies the reviewed device and target firmware
version. The displayed target is captured before asynchronous resume
preparation; offer identity/revision checks and reset permission are unchanged.

The new busy-probe instrumentation case verifies stop remains available and
update actions remain unavailable without uploads or resets. The existing stale
confirmation test also asserts device/version context before checking rejection
of a stale offer. Early emulator boot failures and overlaid ANR captures are
preserved as diagnostic evidence, not visual acceptance results. Artifacts for
this pass are under `work/android-polish015/`; device firmware ZIPs are unchanged.
