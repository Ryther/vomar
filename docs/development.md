# Development

Open the repository in Dev Containers. The public Ubuntu image pins its base,
Python 3.13.12, Node 24 and assistant packages; npm verifies package integrity.
Java 21 runs the existing Kotlin toolchain; Java 17 remains the target. The
normal profile has no host SSH, display, D-Bus or USB mounts. Authentication is
interactive and optional; no assistant is contacted during bootstrap.

`python tools/dev/bootstrap.py workspace` installs locked development tools into
private state. `codex --version`, `opencode --version` and `claude --version`
check the three assistants without login. The canonical guide is under
`.agents/skills/vomar-guide`. Claude uses its relative alias; OpenCode also reads
AGENTS.md and the same skill directory. A Windows checkout with disabled symlinks
uses a hash-owned private fallback; user-customized skills are never overwritten.

Explicit SDK setup:

```sh
python tools/dev/bootstrap.py android
python tools/dev/bootstrap.py firmware
```

Android setup downloads minimal command-line tools with a pinned checksum. Read
and accept Google SDK licenses interactively, then run sdkmanager for android-35
and build-tools 35.0.0. No emulator is installed by default. Firmware setup uses
the 55-project active frozen public west manifest, a separate Python environment and
only the ARM Zephyr SDK toolchain. Nordic binary stack licenses remain applicable.
SDK operations download source/tools and never access a physical target.

For Linux bench access, deliberately select the hardware configuration; review
host USB/D-Bus permissions first. The research configuration is based on a
locally built `vomar-development:local` image and adds analysis tools. Ghidra and
proprietary inputs are optional and are never included in the product runtime.
Do not bind account directories into a shared container.

Sources: [Codex CLI](https://learn.chatgpt.com/docs/codex/cli),
[Android command tools](https://developer.android.com/studio#command-tools),
[NCS](https://github.com/nrfconnect/sdk-nrf),
[Zephyr SDK](https://github.com/zephyrproject-rtos/sdk-ng).
