# Troubleshooting

Start with the app/OS version, selected package, exact error and last operation
phase. Preserve the original backup and session journal. Do not uninstall,
clear data, erase a target or release a halted CPU to make an error disappear.

## Obtainium shows an unknown or wrong version

- **Unknown Latest / placeholder / Last update check: Never:** no successful
  source check has completed. Return to Obtainium's app list and pull down to
  check updates. Inspect any network/API error before pressing Update.
- **A pseudo-version is in use**, or a bundle number in place of the Android
  version: check for the old bundle-tracking configuration. Import the current
  [Vomar configuration](android-updater.md#install-and-track-with-obtainium), which
  reads the native Android version from the release title and keeps OS version
  detection enabled.
- A bundle can change without an Android update. For example, bundle `1.0.0`
  contains Android `1.1.4`. Download filenames do not determine the installed app
  version; check Vomar → Settings.

To migrate an older tracking configuration, re-import the current install link
and run a fresh check; no entry removal or app uninstall is needed. A signature
mismatch requires the matching signed APK; it is not a reason to uninstall. Private originals/journals/credentials can
be lost on uninstall, and automatic Android backup is disabled.

## App installation or startup fails

Verify the download checksum and [supported OS/architecture](installation.md).
Android's package ID and signing identity must match the installed app. Wait for
active operations to end before upgrading over it.

Desktop includes its runtime. Missing Python or an SDK is not a reason for an
end user to install development tools. Retain the exact startup error and check
the matching native package. Platform drivers and Bluetooth/USB permissions
need verification on that OS. See [Desktop](desktop.md).

## A package is rejected or no release is listed

Select the complete firmware ZIP, not a desktop archive, `.ota` carrier or
individual binary. Verify its checksum and native compatibility. Changing the
GitHub source never approves a new firmware signer.

A published project release may contain experimental firmware that ordinary
catalog/fleet routes intentionally reject. Read its known issues and use the
explicit manual route described in [Packages](offline-guide.md). A draft is not
a published release; a missing release does not prevent a compatible local ZIP.
Never alter metadata or substitute components to force admission.

## Bluetooth discovery, connection or pairing fails

Check Bluetooth and the permissions Android requested. Confirm the intended
recovery mode and whether another client owns the connection. A saved name or
advertisement does not identify the target securely.

Distinguish scan, connection, service discovery, pairing, transfer and restart.
A successful earlier step does not prove the next. Preserve existing bonds;
do not delete them, repeat resets or assume the PIN is wrong without evidence.
Use [Bluetooth update report export](android-bluetooth-trial.md#interrupted-attempts)
and retain the exact failed phase before reviewing another attempt.

## Broker connection fails or device information is stale

Check the active profile, exact host/port/transport, credentials and base topics.
Plaintext local connections need separate consent; port 8883 alone does not
prove TLS. Desktop uses the OS credential store without plaintext fallback.

Android restores an activated connection and subscriptions when opened. Choose
**Retry connection** or **Save and reconnect** after correcting a configuration
error. **Disconnect** disables restoration. Values marked **(saved)** are
historical; wait for fresh reports. A generic OTA flag or cached firmware version
does not establish update eligibility.

## Upload, first installation or restart was interrupted

Open the matching Activity/session record. Keep the same package, original and
journal. Never capture partially rewritten FLASH as a new original or delete a
journal to remove the interruption state.

Explicit repair/resume checks the same target and bytes, then requests fresh
review. Changed originals, corrupt journals or unknown memory block repair.
Successful first-install readback intentionally leaves the CPU halted; start is
a separate action. An acknowledged start/reset is not observed lamp operation.
See [First-install repair](android-first-install.md#explicit-repair-after-an-interrupted-installation)
and [Bluetooth interruptions](android-bluetooth-trial.md#interrupted-attempts).

Older Android 1.0.7 can report **Syntax error in regexp pattern** while reading
start evidence. Once the active operation has ended, upgrade over the app with
the matching signer. Existing originals and journals must be preserved; the
error alone does not establish FLASH or CPU state.

## Stop was pressed during a Zigbee update

A submitted OTA request can continue in Zigbee2MQTT after the client stops.
Retain the uncertain session/network and perform explicit read-only
reconciliation before another operation. A retained broker message alone is
not completion evidence.

## A dimmer restarts unexpectedly

Source candidate firmware 1.1.6 adds the original SDK error code and severity to
the existing reboot diagnostics. When the SDK supplies a verifier location, the
record also retains its file ID and line before a later generic assertion. This
collects evidence; APS-105-5241 remains unresolved. It is a bounded first-cause
record, not a continuous activity log. Already stored reports from older firmware
cannot acquire a missing original error after the update.

With a matching Zigbee2MQTT converter and firmware schema 7 or later, request
`fault_diagnostic_status` and each `fault_diagnostic_0` through
`fault_diagnostic_7` using the device's read-only `/get` route. Request each
32-byte fragment separately and collect fresh replies. The fragments are
available to `/get` even though they are hidden from ordinary UI controls. Save
the complete state JSON privately before another update. A cached status or
partial set of fragments is insufficient to decode a report.

A new fatal record is saved durably at the next healthy startup, after storage
write and readback. Status bit 1 means capture is ready; bit 2 means a report is
present; bit 8 means a storage error; bit 16 means an earlier pending capture
must be preserved; bit 32 marks a report from a different build. Such an older
report must be matched to its own archived build. Do not clear settings or
repeatedly power-cycle the device to force a new report: retained RAM can be lost
on a power cut, and this is not a repair procedure.

For a developer with the matching source, decode the saved JSON offline:

```sh
python -m tools.firmware.read_fault_diagnostics exported-state.json
```

The decoder checks the record format, CRC and capture consistency. Match its
`build_id` to the archived ELF before interpreting addresses or comparing causes.
See [original SDK diagnostics](https://github.com/Ryther/vomar/blob/main/firmware/README.md#original-sdk-error-diagnostics)
for fields and capture limits. Exporting client update reports or Bluetooth
recovery history is a different diagnostic and does not collect these Zigbee
reboot fragments automatically.

## Development tools or CI fail

Use [Development](development.md) for Docker/socket/SSH problems and
[GitHub setup](github-setup.md) for required checks, credentials and Sonar.
A missing compiler, scanner report or coverage file is a failed check, not
physical evidence. Do not expose private credentials to reproduce a PR failure.

## Report a problem safely

Include app/OS and package versions, exact phase, sanitized error and reproduction
steps. Review diagnostic exports before private sharing: they may identify the
device or setup. Never post original images, signing material, passwords, raw
broker captures or household identities in public issues.
