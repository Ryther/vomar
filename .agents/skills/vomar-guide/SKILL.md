---
name: vomar-guide
description: Develop, test, package or maintain Vomar firmware, Android and desktop clients or their coordinated GitHub distribution.
---

Read AGENTS.md and CONTRIBUTING.md first. Hardware and acquired evidence have
separate authorization from software development. Never program, erase, recover
or start a physical target merely to run tests.

- The distribution VERSION is independent of firmware and Android versions.
- Runtime admission uses signed packages and authenticated live identity. A
  GitHub filename, remembered device label or checksum is not authorization.
- Preview and consent are specific to package, operation, live target and original.
  Restart, cancellation and uncertainty require fresh review; no persistent yes.
- Preserve acquired originals, export/reopen receipts, UICR and halted-target
  uncertainty. Never automatically release a target after a failed transaction.
- Run public source checks with `python -m tools.release.public_tree`; add exact
  authored file exceptions, never admit private work directories or credentials.
- See docs/development.md for tooling and docs/releasing.md for distribution.
  Physical qualification and native BLE/USB checks are recorded separately.

Use `python tools/dev/bootstrap.py workspace` after changing tooling locks.
Agent login belongs to private state; do not add account settings or wrappers.
