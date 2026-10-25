# Android updater language

Historical scope: Italian copy for app 0.1.3. The current app 1.0.0 uses
the English interface described in [the updater guide](android-updater.md).
These earlier wording decisions do not describe the current UI.

## Terminology

| Term | Meaning in the interface |
| --- | --- |
| Dimmer | The physical device identified by the imported package. |
| Pacchetto ZIP | The local, signed update package intended for that dimmer. |
| Firmware | Executable software on the dimmer; avoid “immagini” in the normal flow. |
| Recupero Bluetooth | The independent maintenance mode used to connect and update. |
| Verifica Bluetooth | A connection and firmware-state check without firmware upload or reset. |
| Avvia aggiornamento | Begin an update that has no saved session. |
| Riprendi | Verify the device and continue a previously started update. |
| Interrompi | Stop subsequent requests while retaining saved progress; this cannot cancel internal copying or a reset already started. |
| Dimmer online | A result the operator checks in Home Assistant or Zigbee2MQTT and records in the app. |
| Dettagli tecnici | Package/device identifiers and hashes; not instructions the owner must interpret to proceed. |

## Message rules

- Show the operation and next action before technical detail. Do not present
  internal enum names, protocol acronyms or class names as progress labels.
- After Android pairing, ask the owner to wait for the app's result. Use
  Riprendi only after interruption, not as a mandatory pairing step.
- Connection errors shared by the diagnostic probe and update flow should say
  to retry the operation, rather than direct every owner to resume an update.
- Describe transferred firmware verification separately from a reset request
  acknowledgement and from the operator's online confirmation. None of these
  alone proves the others.
- A missing reset acknowledgement does not prove a failed reset. The dedicated
  confirmation still authorizes at most one new attempt, subject to the existing
  verified-state policy.
- Unknown failures retain technical detail for diagnosis. Do not invent a
  cause such as a wrong PIN, bad radio signal or a defective dimmer.
- UI strings belong in Android resources where possible. Runtime event wording
  is isolated in `UpdateCopy`, separate from the coordinator's authority.

## Implementation and limits

App 0.1.3 updates labels, preparation instructions, error recovery text,
notifications, progress wording and the reset confirmation. The package summary
names the firmware to install; the helper's version is labelled “Programma di
migrazione” in technical details, rather than implying it is the installed
recovery version.

The scan, authentication, identity/hash checks, signed firmware packages, saved
session rules and reset authorization are preserved. Real Android 16 pairing
remains a separate diagnostic task; a copy pass does not establish that it works.

Software evidence and render captures for this pass are stored locally under
`work/android-clarify013/`; signed APK and audit report are under
`experiments/android-updater/20261023-clarify-013-final/`. Emulated BLE is not evidence
of a real radio transfer or of a working lamp.

Verification: 43 core and 79 app JVM tests, 41 Python tests, release lint and APK
signature/content checks passed. The API35 emulator ran the full 12-test suite
before the final short reset label/status-detail presentation adjustment; the
final source then passed 3 targeted UI tests at font scale 2.0 (bounds, read-only
probe and stale reset authorization). Render captures cover a 480×800 phone,
normal/200% text and the system night setting. The incumbent fixed light theme
is preserved; this pass does not introduce dark theming. Early cold-boot System
UI ANR artifacts are retained separately and are not successful UI evidence.
