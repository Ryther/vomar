# Vomar documentation

![Vomar — Independent open-source firmware](images/vomar-banner.png)

Vomar manages compatible Vimar 30805 dimmers with custom firmware, Android and
desktop clients, and an optional Zigbee2MQTT converter. It is independent of Vimar.

## Install and use

Start with **[Install Vomar](installation.md)**. No device, broker, development
SDK or GitHub account is needed to install the app.

| Your task | Guide |
| --- | --- |
| Install Android or move from a manually installed APK to Obtainium | [Android](android-updater.md#install-and-track-with-obtainium) |
| Install Linux, Windows or macOS software | [Desktop](desktop.md#install) |
| Connect Android to Zigbee2MQTT | [Android connections](android-updater.md#automatic-zigbee2mqtt-connection) |
| Update one already-custom dimmer | [Bluetooth update](android-bluetooth-trial.md) |
| Join a Zigbee network or enter Bluetooth service | [Connection modes](connection-modes.md) |
| Understand a rejected package, failed connection or interruption | [Troubleshooting](troubleshooting.md) |
| Preserve originals and choose the correct ZIP | [Packages and recovery](offline-guide.md) |
| Install custom firmware for the first time with a DK | [First installation](android-first-install.md) |

Installing a client never installs device firmware automatically. Experimental
firmware needs its explicit manual route and fresh device review. Keep each
original backup independently of the app; Android uninstall deletes private data.

## Develop and research

- [Contribute](../CONTRIBUTING.md) and [set up the development container](development.md).
- [Architecture](architecture.md) and [client support](desktop-parity.md).
- [Release a bundle](releasing.md) and [configure GitHub](github-setup.md).
- [Zigbee controls](zigbee-controls.md) and [OTA reference](zigbee-ota.md).
- [Research evidence](research-summary.md), [known facts](known-facts.md) and
  [open hypotheses](hypotheses.md).

Guides describe the source revision you are reading. Check the exact release
manifest for delivered component versions and qualification. Historical research
and an earlier successful bench trial do not certify a newer package.
