# Development

Open the repository in Dev Containers. The public Ubuntu image pins its base,
Python 3.13.12, Node 24 and assistant packages; npm verifies package integrity.
Java 21 runs the existing Kotlin toolchain; Java 17 remains the target. The
normal profile has no host SSH, display, D-Bus or USB mounts. Authentication is
interactive and optional; no assistant is contacted during bootstrap.

All three profiles include Docker CLI/Buildx and GitHub CLI through official
Dev Container Features pinned by OCI digest. Their CLI versions are selected
explicitly. The Docker feature mounts the host's `/var/run/docker.sock` at
`/var/run/docker-host.sock` and initializes non-root access. Docker commands use
the host daemon, including access to other local containers. GitHub login state
has its own private named volume; credentials are never built into the image.

The public profile must be built/reopened through Dev Containers so its Features
and mounts are applied. A plain build of `.devcontainer/Dockerfile` produces only
the base toolchain image. To build the complete public development image:

```sh
npx --yes @devcontainers/cli@0.89.0 build --workspace-folder . --image-name vomar-development:local
```

Creation and startup run `python tools/dev/container_check.py`. It requires a
real mounted socket, a reachable Docker server and working `docker`/`gh` tools.
It checks versions without GitHub login, hardware access or agent inference. A
regular zero-byte `/var/run/docker-host.sock` is an unmounted image placeholder:
the configuration must be applied using **Dev Containers: Rebuild Container**.
Recreation interrupts the current container sessions, so save active work first.
Changing the JSON or restarting the forwarding proxy alone cannot add a mount to
an already running container.

The public profile's complete image build/reopen still needs live verification;
static checks and mocked daemon responses do not establish that it boots.

`python tools/dev/bootstrap.py workspace` installs locked development tools into
private state. `codex --version`, `opencode --version` and `claude --version`
check the three assistants without login. The self-contained end-user guide is under
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
