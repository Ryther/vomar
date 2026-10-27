# Vomar

![Vomar — Independent open-source firmware](docs/images/vomar-banner.png)

> **AI-assisted code warning:** This project includes code produced with AI coding
> agents. Tests and reviews do not establish that it is safe or correct on your
> hardware. Preserve each device's original backup and use an isolated, explicitly
> authorized qualification procedure before trusting a firmware candidate.

[![CI](https://github.com/Ryther/vomar/actions/workflows/validate.yml/badge.svg?branch=main)](https://github.com/Ryther/vomar/actions/workflows/validate.yml)
[![CodeQL](https://github.com/Ryther/vomar/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/Ryther/vomar/actions/workflows/codeql.yml)
[![Sonar quality gate](https://sonarcloud.io/api/project_badges/measure?project=Ryther_vomar&metric=alert_status)](https://sonarcloud.io/dashboard?id=Ryther_vomar)
[![Documentation](https://github.com/Ryther/vomar/actions/workflows/pages.yml/badge.svg?branch=main)](https://github.com/Ryther/vomar/actions/workflows/pages.yml)
[![Latest release](https://img.shields.io/github/v/release/Ryther/vomar)](https://github.com/Ryther/vomar/releases/latest)
[![License](https://img.shields.io/github/license/Ryther/vomar)](LICENSE)

Vomar provides custom nRF52840 firmware, Android and desktop updater clients,
and a Zigbee2MQTT converter for compatible Vimar View Wireless Linea 30805
hardware. It retains the original secondary power-controller firmware. This is
an independent project, not an official Vimar product.

## Current status

Firmware **1.0.0 is a signed qualification candidate** with thirteen physical
qualification checks still pending. Its bounded standalone-DK runtime trial
passed within the recorded scope; it does not qualify initial installation,
stock restoration, power-cut recovery or physical dimmer behavior. Earlier
successful trials apply to their recorded versions and routes.

The Android version owner is the app's Gradle configuration (currently 1.0.6,
versionCode 26). Firmware, Android, desktop and the coordinated distribution
have independent versions. The distribution manifest starts at 0.0.0; this
checkout does not certify a published distribution or active remote services.
Badges summarize their linked services and do not prove physical qualification.

## Start here

- [Install, configure, update or remove a client](docs/installation.md).
- [Android behavior and compatibility](docs/android-updater.md),
  [first installation](docs/android-first-install.md) and
  [Bluetooth qualification trials](docs/android-bluetooth-trial.md).
- [Desktop GUI and CLI](docs/desktop.md), sharing one engine. Native package
  targets are Linux x64, Windows x64 and macOS Apple Silicon (arm64); platform-specific
  BLE/USB behavior still needs its own acceptance evidence.
- [Troubleshooting and interrupted work](docs/troubleshooting.md).
- [Documentation home](docs/index.md) and
  [architecture](docs/architecture.md).

AI assistants can use the self-contained
[Vomar user guide skill](.agents/skills/vomar-guide/SKILL.md) to explain setup,
verification, recovery and removal without a checkout. Codex and OpenCode use
its canonical `.agents/skills/` source; Claude's tracked alias points to the
same guide. You can also provide that Markdown as conversational instructions;
it grants neither device access nor consent to program hardware.

## Source, artifacts and private data

Git contains authored source, public docs, public verification keys and reviewed
synthetic fixtures. APKs, signed firmware ZIPs, OTA carriers and native packages
belong in verified GitHub Release assets with checksums and qualification scope.
A valid signature proves package integrity and signer identity, not working
hardware. Ordinary client routes reject qualification candidates.

Keep original vendor APK/firmware, per-device backups, network data, diagnostics,
credentials and private signing keys outside public Git and archives. Each
device's original is private recovery material, separate from a shared release.
The [research summary](docs/research-summary.md), [known facts](docs/known-facts.md)
and [hypotheses](docs/hypotheses.md) distinguish observations and uncertainty.

## Develop and contribute

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md). Open the
tracked [Dev Container](docs/development.md): the default profile includes
Docker/Buildx, gh, Codex, OpenCode and Claude. Credentials remain private and
login is separate from installation. Follow the rebuild and smoke checks in the
guide; configuration presence does not prove the container boots.

Inside the pinned development environment, start with:

```sh
python tools/dev/bootstrap.py workspace
/home/vscode/.cache/vomar/dev-venv/bin/python -m pytest tools/release/tests tools/dev/tests
```

Desktop/GUI, firmware, Android, converter, coverage and security checks have
additional dependencies and commands in [CONTRIBUTING.md](CONTRIBUTING.md).
Use disposable services and synthetic inputs. Artifact-dependent skips are
reported as skips and do not establish physical qualification.

[Releasing](docs/releasing.md) explains exact-candidate drafts and immutable
assets; [GitHub setup](docs/github-setup.md) describes remote configuration and
verification. Release Please owns distribution proposals. Physical programming,
erasure and UICR/bootloader changes require separate explicit operator approval.

[MIT license](LICENSE), copyright 2026 Ryther. Dependencies retain their own
licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).
