# Contributing to Vomar

Use the public Dev Container and its pinned tool environments. Normal
development needs no household configuration or attached hardware. Source,
comments, documentation and Conventional Commit messages are English.

Read AGENTS.md and the component guide before changing an operation's public
contract. Keep validation, operation ownership, transports and presentation
separate. Describe the user-visible trigger, resulting behavior and actual
verification in a pull request.

## Verification

Inside the Dev Container, set up the locked development environment:

```sh
python tools/dev/bootstrap.py workspace
VOMAR_PYTHON=/home/vscode/.cache/vomar/dev-venv/bin/python
"$VOMAR_PYTHON" -m pytest tools/release/tests tools/dev/tests
"$VOMAR_PYTHON" -m tools.release.check_workflows
"$VOMAR_PYTHON" -m tools.release.branding --check
"$VOMAR_PYTHON" -m mkdocs build --strict
```

For desktop/GUI checks, install `requirements-desktop.lock` in a disposable
Python 3.13 environment, install this project with `--no-deps`, and run
`python -m pytest apps/desktop-updater/tests` (`QT_QPA_PLATFORM=offscreen` for
headless UI checks). Do not overlay those runtime dependencies into the SDK.
The broader self-contained firmware/Android host suites are
`python -m pytest tools/firmware/tests tools/hardware/tests tools/android/tests`.
Run `npm test --prefix integrations/zigbee2mqtt` for the converter. Native
firmware and Android builds additionally require the explicit SDK setup in
[Development](docs/development.md). Their authoritative CI commands are in
`.github/workflows/validate.yml` and `security.yml`.

Run
relevant focused tests while working and all affected required checks before
handoff. Preserve reported skips: unavailable private artifacts and physical
tests are not successful qualification.

Use synthetic packages, disposable MQTT brokers and transport simulators.
Never point automated tests at household services or a physical DK/device.
Physical programming, erasure and UICR/bootloader changes require explicit
operator authorization; no contribution or container bootstrap grants it.

## Public files and dependencies

The ignore policy denies new files by default. Add exact exceptions only for
reviewed authored files; do not use force-add. Keep protected originals,
acquired firmware, research output, diagnostics, credentials and private signing
keys outside public Git and archives. Preserve useful tests and reviewed
synthetic fixtures. Inspect staged paths and run the public-tree check.

Review complete lock changes and coupled upstream SDK graphs. Do not auto-merge
dependency proposals or override individual SDK-owned pins to make a build
green. Test a proposed graph before updating the published version catalog.

## Documentation and user flows

Update affected installation, configuration, recovery and troubleshooting
procedures with the final behavior. Include prerequisites, the complete action,
observable success, failures and retained-data consequences. Exercise UI/CLI
journeys and capture the rendered revision before claiming UX validation.
Keep the canonical user guide aligned with both clients.

## Releases

Release Please owns the distribution version/changelog and proposed tags;
component versions and qualification remain independent. A draft must identify
one exact commit and all required signed/verified artifacts before publication.
Do not move published tags, overwrite differing assets or convert host test
results into physical qualification. Signing and publication credentials never
enter untrusted PR execution or shared examples.

## Pull request analysis

The PR template records the tested SHA, commands/results, user journeys,
documentation impact and unverified scenarios. Keep the self-contained
`.agents/skills/vomar-guide/SKILL.md` aligned with user procedures, not merely
with contributor commands; Claude's alias points to the same source.

`Sonar required` is produced on PRs after actual Python, JavaScript and Kotlin
coverage. Trusted same-repository PRs use Cloud with protected base settings;
fork/Dependabot PRs use disposable Community without repository credentials.
Both publish report artifacts. Missing coverage, the expected scanner or its
report fails the aggregate. Firmware C has mandatory CodeQL; full main/release
Sonar additionally requires actual C compilation/coverage and exact revision.
A scoped PR scan does not certify full release analysis or hardware behavior.

Workflow/settings changes take effect from the trusted base after merge. The
initial infrastructure baseline must be reviewed and established before making
its new PR checks mandatory; do not execute bootstrap PR helpers with secrets.
Pages publication is opt-in with `ENABLE_PAGES=true`. Build the site locally
with the locked environment, follow install → verify → troubleshoot and
contribute → checks → release links, and review rendered navigation after
changes. A local strict build does not prove Pages is deployed.
