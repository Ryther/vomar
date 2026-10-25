# Contributing to Vomar

Use the public Dev Container and its pinned tool environments. Normal
development needs no household configuration or attached hardware. Source,
comments, documentation and Conventional Commit messages are English.

Read AGENTS.md and the component guide before changing an operation's public
contract. Keep validation, operation ownership, transports and presentation
separate. Describe the user-visible trigger, resulting behavior and actual
verification in a pull request.

## Verification

The existing self-contained source checks are documented in README.md. Run
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
