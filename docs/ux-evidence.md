# UX evidence

The desktop follows the existing Android vocabulary and approved palette. Actual
Qt offscreen tests exercise all three destinations, persistent entered target,
keyboard focus and Stop. A rendered 1080×720 light-theme Devices screen was
inspected during implementation; screenshots use empty/synthetic private state.

The CLI is executed outside the source tree from the actual Linux frozen bundle
for version/help and read-only package contracts. Native build workflows repeat
launch/core checks per OS. These checks do not prove Bluetooth pairing, USB
permissions, native dialogs, macOS first-launch approval or physical operation.

## Brand artwork integration

The supplied Vomar artwork is pinned by its original hashes. The logo was
rendered in light and dark Qt layouts, loaded from an installed Python wheel
outside the checkout, and exercised in the Linux frozen GUI. The actual Linux
package was installed and removed under disposable paths containing spaces and
Unicode; all eight installed icon copies matched their originals and private
state survived removal. Desktop and mobile browser captures of the built
documentation verified its logo, banner and favicon.

Four focused Android branding checks passed on an API 35 software emulator:
light/dark Settings at 320×640 and an expanded 1280×800 viewport with 130% font
scale. They verify the installed application label, adaptive launcher drawable,
fully visible brand symbol and application window before retaining captures.
The packaged PNG preserves every source pixel and its alpha channel. These are
UI checks, not a full instrumentation run or BLE/USB qualification. Initial
emulator launcher ANR captures were rejected; the final captures have no overlay.

Windows and macOS icon packaging has source review but still requires native
build and visual evidence. At the existing 760×560 desktop minimum, the Devices
body has overlapping fields; comparison against unmodified source confirmed
identical geometry before this artwork integration. The header, status and Stop
remain visible. This existing compact-layout issue is separate unfinished UX
work; private captures and the handoff remain outside public source.

Before release, retain screenshots and test reports from the exact candidate for
empty/offline, review denial, interrupted session, Stop, repair, MQTT credential
failure and long names at supported window sizes/themes. Never include household
data in public screenshots. Do not mark a pending journey complete from intended
layout or source configuration alone.
