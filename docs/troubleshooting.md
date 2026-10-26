# Troubleshooting and recovery

Start with the app version, selected package, exact symptom and last recorded
operation phase. Preserve the original backup and session journal. Do not erase,
recover, rewrite UICR, reinstall stock firmware or release a halted target as a
generic troubleshooting step.

## App installation or startup fails

Check OS/architecture against [installation](installation.md) and verify the
downloaded distribution checksums. For Android upgrades, a signer mismatch is
not solved by approving a different identity or deleting the existing app's
state. Obtain the matching signed APK and preserve originals before considering
any uninstall.

Desktop packages contain their runtime. A missing Python/SDK on the end-user
machine is not a reason to install development tools. Capture the startup error
and check the matching native package and OS contract in [Desktop](desktop.md).
Native drivers, first-launch dialogs and Bluetooth permissions need verification
on that platform; success on Linux does not establish Windows/macOS behavior.

## A package is rejected or no release is listed

Confirm that you selected the canonical firmware common ZIP, not a desktop
archive, OTA carrier or individual image. Check the download source, size/hash
and package version. The app's public trust anchor is independent of GitHub;
changing the download URL does not authorize a new signer.

A qualification candidate is intentionally rejected by online release/fleet
routes. Android 1.0.6 has one manual firmware chooser with explicit local/beta
review; desktop has a separate qualification route. Do not remove metadata or
substitute binaries to bypass either client's image/compatibility checks. An empty release list can be a genuine current
state: a local signed package remains usable without a GitHub token. Do not
invent a release or treat an empty list as proof of a Bluetooth failure.

## Bluetooth discovery, connection or pairing fails

Check that Bluetooth is enabled and the app has the OS permissions it requested.
Confirm which target/recovery version is actually present and whether another
client owns the connection. A device name alone is not identity. Preserve
existing bonds; do not delete them or repeat resets to force pairing without
understanding the exact recovery's contract.

Distinguish discovery, connection, service discovery, pairing, upload and restart.
A successful earlier phase does not prove the next. For the separate Android
qualification tool, [Bluetooth trial](android-bluetooth-trial.md) describes report
export and its diagnostic limits. Stop and collect the recorded phase before
retrying an uncertain transfer.

## Broker connection fails or device information is stale

Check the active saved connection, exact host/port, transport, broker credentials
and Zigbee2MQTT base topics. For an unencrypted local connection, confirm the
separate consent. Do not paste passwords or expanded configuration into an issue.

Unlock the desktop OS credential store if it is unavailable; there is no
plaintext password fallback. Saved/retained device metadata may remain visible
while disconnected. On Android, readings marked `(saved)` are historical.
Reconnect explicitly and inspect the new result. Neither a cached firmware
version nor generic OTA support proves that an update is currently admissible.

## Upload, first installation or restart was interrupted

Use Activity/session details to identify the exact target, package, original
and last durable phase. Stop and retain that state. Do not start an unrelated
new installation, acquire a replacement original from partially modified FLASH
or assume that a submitted reset completed successfully.

Explicit resume/repair must revalidate the same target, original and release,
then request fresh review. Missing/corrupt journals, unknown bytes or changed
originals block repair. Successful FLASH readback may intentionally leave the
CPU halted; start is a separately reviewed action. Android 1.0.6 retains the original privately on the phone and associates it
with the device; exporting an independent copy is optional but needed to retain
recovery material across app-data deletion or uninstall. See
[Android first installation](android-first-install.md) and
[Desktop first installation and repair](desktop.md#first-installation-and-repair).

## Stop was pressed during a Zigbee update

Stopping the local client does not revoke an OTA request already submitted to
Zigbee2MQTT. Preserve the uncertain session/network and use the read-only
reconciliation path before admitting another operation. A retained broker
message alone is insufficient evidence that installation or recovery finished.

## Docker or development tools fail

Follow [Development](development.md). Inside the actual Dev Container, check
`docker version` and `gh --version`; authentication is a separate step. An EOF
or unreachable daemon with only a client version is an environment failure.
Use Rebuild/Reopen to apply Features and socket mounts; restarting an old proxy
cannot add a missing mount. Do not expose account credentials to a contributed
Dockerfile merely to reproduce a failure.

For a failed Sonar PR check, inspect coverage inputs, the chosen Cloud/Community
job and its linked artifact. A missing report is a failure. Community's PR
scope is Python/JavaScript/Kotlin; firmware C has mandatory CodeQL and full
protected main/release Sonar. The release gate still requires an analysis of
the exact candidate SHA. See [GitHub setup](github-setup.md).

## Report a problem safely

Include client/OS versions, package/distribution version, operation phase,
sanitized error, reproduction steps and which checks were actually performed.
Use a synthetic example where possible. Review an exported diagnostic report
before sharing it privately: it may contain device identity or environmental
details. Never attach original device images, signing material, credentials,
raw broker captures or household identifiers to a public issue.

State what remains uncertain. A checksum, source test, green badge or transfer
acknowledgment cannot establish physical dimmer behavior or release qualification.
