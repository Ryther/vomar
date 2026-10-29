# UX validation evidence

Use this page to interpret interface evidence and plan exact-candidate review.
It records the scope of earlier observations; current acceptance requires the
actual revision, commands, renders and unverified journeys in the PR report.
See [development](development.md) for reproducible checks.

## Evidence already observed

Historical Qt offscreen checks exercised Devices, Activity, Settings, retained
entered targets, keyboard focus and Stop. A 1080×720 light Devices render was
inspected using empty/synthetic state. A frozen Linux CLI was launched outside
the checkout for help/version and read-only package checks. Native workflows
repeat launch/core checks on their target OS; those are software observations.

Brand integration was rendered in light/dark Qt, an installed wheel and the
Linux frozen GUI. The Linux package was installed/removed in disposable paths
with spaces and Unicode; icon bytes matched and private state survived that
Linux removal. This does not establish Android uninstall persistence.
Built documentation was viewed in desktop/mobile browsers.

Four focused API 35 Android emulator branding cases checked light/dark Settings,
a 320×640 phone and expanded 1280×800 view with 130% font scale. They checked the
application label, adaptive icon, visible symbol and application window. Captures
with System UI ANR overlays were rejected. These cases were not a full device or
instrumentation qualification campaign.

## Known gaps

A historical 760×560 desktop render had overlapping Devices body fields; the
same geometry existed before the artwork change. The header, status and Stop
remained visible. Keep this compact-layout defect open until the exact repaired
layout is rendered and exercised. Private diagnostic captures are not required
inputs for contributors.

Windows/macOS visual behavior, real Bluetooth and USB permissions/drivers,
macOS first-launch approval, native dialogs and physical firmware operation need
separate evidence. Offscreen or emulator results cannot establish these.

## Review a candidate

Exercise empty/offline state, review denial, interrupted session, Stop, repair,
MQTT credential failure and long names at supported sizes, text scales and
light/dark/system themes. Confirm focus order, accessible names and usable action
bounds. Capture the exact source/artifact identity and distinguish assertions
from visual inspection. Use synthetic identities and disposable services; never
publish household data, originals, credentials or private journals in screenshots.
