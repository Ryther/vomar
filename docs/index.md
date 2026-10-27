# Vomar documentation

![Vomar — Independent open-source firmware](images/vomar-banner.png)

Vomar is an independent firmware and updater project for compatible Vimar 30805
dimmers. A coordinated distribution contains firmware, Android, desktop GUI/CLI
and a Zigbee2MQTT converter. Firmware 1.0.0 remains a qualification candidate;
its thirteen physical checks are pending. Installing a client or checking source
code does not qualify a physical device.

## What do you want to do?

- **[Install or update the client](installation.md):** Choose Android or the
  matching native desktop package and verify first startup.
- **[Use Android](android-updater.md)** or **[use desktop GUI/CLI](desktop.md):**
  Select a package, connect deliberately and review an operation.
- **[Fix a problem](troubleshooting.md):** Diagnose a failure or interrupted
  session while preserving originals and uncertain target state.
- **[Understand package and recovery rules](offline-guide.md):** Distinguish
  shared firmware from device-private originals and operation consent.
- **[Review first installation](android-first-install.md)** or a
  **[Bluetooth qualification trial](android-bluetooth-trial.md):** Separate,
  explicitly authorized procedures with physical checks still pending.
- **[Give an assistant the user guide](https://github.com/Ryther/vomar/blob/main/.agents/skills/vomar-guide/SKILL.md):**
  Self-contained setup, diagnosis, upgrade and removal guidance.

## Contribute or understand the design

- [Architecture](architecture.md): component ownership, trust and persistence.
- [Development](development.md) and [contribution rules](../CONTRIBUTING.md):
  container, test environments, commands and review evidence.
- [Release a distribution](releasing.md) and [configure GitHub](github-setup.md):
  version proposals, exact candidate checks, credentials and publication.
- [Research evidence](research-summary.md): confirmed observations, hypotheses
  and remaining hardware limits.

The guides track repository source. Compare installed app/package versions with
release notes before applying steps from a newer revision. A downloaded package,
green badge or acknowledged reset does not prove physical operation.
