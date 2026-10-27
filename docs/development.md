# Development

Open `.devcontainer/devcontainer.json` in Dev Containers. This is the only
supported development configuration: firmware, Android, desktop, hardware and
research work use the same container. Install additional tools there as needed;
there is no hardware/research profile to switch to.

The Ubuntu image pins Python 3.13.12, Node 24 and assistant packages; npm verifies
package integrity. Java 21 runs Kotlin; Java 17 remains the target. Git and the
OpenSSH client, Docker CLI/Buildx, GitHub CLI, Codex, OpenCode, Claude and the
Linux GUI runtime are available. Startup checks Docker, gh and `ssh -V` without
logging in, contacting an assistant or opening hardware.

Docker and gh use official Dev Container Features pinned by OCI digest. The
Docker feature mounts `/var/run/docker.sock` at `/var/run/docker-host.sock` and
initializes non-root access. Docker commands use the host daemon. A plain build
of `.devcontainer/Dockerfile` does not apply those Features; build/reopen through
Dev Containers. For an image build:

```sh
npx --yes @devcontainers/cli@0.89.0 build --workspace-folder . --image-name vomar-development:local
```

`python tools/dev/container_check.py` requires a real mounted Docker socket, a
reachable daemon and working Docker, gh and SSH executables. A regular zero-byte
Docker socket placeholder means the bind mount was not applied. Save active work
before recreating the container; changing JSON or restarting the forwarding
proxy cannot add mounts to a running container. `Devcontainer required` builds
and reopens the complete configuration for the candidate revision.

## Persistent state and Git authentication

Named volumes preserve the SDK cache, Gradle cache, GitHub login and assistant
state. Codex uses `/home/vscode/.codex` on `vimar-30805-codex`, preserving the
existing project's session volume. Claude/OpenCode retain their separate paths
inside `vomar-agent-state`. Keep these volumes when rebuilding; deleting them is
not part of setup. Existing account state is never copied into an image.

For SSH Git access, start the host's SSH agent with your existing key before
opening VS Code. Dev Containers can forward the agent; no private-key directory
is mounted by this configuration. `ssh -V` checks the client, while
`git ls-remote origin` verifies the actual repository access. Installing gh or
SSH does not authenticate either one. HTTPS gh login remains available and its
state has the separate `vomar-github-state` volume.

`python tools/dev/bootstrap.py workspace` installs locked development tools.
`codex --version`, `opencode --version` and `claude --version` check installation
without inference. The canonical user guide is `.agents/skills/vomar-guide`;
Claude's alias and the hash-owned private fallback preserve user-customized
skills. Existing session histories can be selected with `codex resume --all`
when the workspace path changes.

## Add tools in the same container

```sh
python tools/dev/bootstrap.py android
python tools/dev/bootstrap.py firmware
python tools/dev/bootstrap.py research
```

Android setup downloads minimal command tools with a pinned checksum. Accept SDK
licenses interactively, then install android-35 and build-tools 35.0.0 as printed
by the helper. Firmware setup uses the 55-project frozen public west manifest,
a separate Python environment and only the ARM Zephyr SDK toolchain. Research
setup installs gdb-multiarch, binwalk and wireshark-common; install a reviewed
Ghidra release separately. These steps do not rebuild/switch containers, open
hardware or import proprietary evidence. Nordic binary-stack licenses apply.
An emulator is added by CI for synthetic Android UI coverage, not installed by
default in the development image.

Android Gradle tests generate signed synthetic fixtures with Python using the
locked `pytest` and `cryptography` packages in `requirements-dev.lock`. Workspace
bootstrap installs these packages; set `VOMAR_PYTHON` to that environment's Python
when invoking Gradle from another shell. Device coverage uses an isolated API 35
emulator and the synthetic first-install UI/adapter tests. Ordinary unit tests
and `jacocoDebugReport` never start an emulator or access physical hardware.

## Optional Linux bench connections

Use the same configuration. To expose Linux USB and the system D-Bus socket,
set the following in the host shell **before the first container creation**, and
open VS Code from that shell:

```sh
export VOMAR_USB_DEVICE=/dev/bus/usb
export VOMAR_DBUS_SOURCE=/run/dbus
code .
```

Review host USB/plugdev and D-Bus access first. Without these variables, the
container maps only `/dev/null` and an empty private D-Bus volume, so CI and
ordinary development do not require attached hardware or host services. Changing
host mounts later requires recreating this same configuration after saving work;
it never requires another profile. Access does not authorize programming,
erasure, scanning at startup or recovery. Tests use synthetic targets only.

The development SDK runs in Linux; Windows contributors can use a WSL2 workspace.
The native application packages are separately built/tested on their target OS.

## Native CI prerequisites

Linux GUI tests need the operating system's GL/EGL runtime before importing
PySide6, including in offscreen mode. The desktop and UX jobs install those
libraries before tests; packaging prerequisites installed later cannot repair an
earlier import failure.

The supported desktop targets are Linux x64, Windows x64 and macOS Apple Silicon.
Each native runner builds and checks its own package, including frozen CLI,
signed-package verification and GUI smoke checks. Linux checks cannot establish
another native platform's hardware behavior; actual qualification remains
separate from hosted build and smoke results.

Firmware and native CodeQL jobs reclaim unused Android/.NET/Haskell SDKs only
on disposable GitHub-hosted runners and require 30 GiB free before setup. They
retain the CodeQL tool cache, the pinned Nordic graph and all product profile
builds. Build parallelism is capped at two; no cleanup step runs in the public
Dev Container. If capacity is still insufficient, inspect disk usage and the
failed build before choosing another runner; do not omit profiles or extraction.

CodeQL's shared source paths must exist in every interpreted job. Generated
firmware snapshots are captured by the C build's compiler tracing and checked
against the original product source archive, rather than included as nonexistent
paths in Python extraction. Successful uploads also require the GitHub code
scanning configuration described in [GitHub setup](github-setup.md).

Host C coverage instruments only durable firmware sources, including inline
functions in that source tree. Disposable test harnesses and synthetic SDK
headers are excluded before compilation. GCC maps and executed profiles must
still match exactly, and gcovr errors remain fatal. Run the actual native suites
and produce XML with:

```sh
python -m tools.release.c_coverage --output _test/c-coverage
```

Use a new output directory for each run so older execution profiles cannot
stand in for the current candidate's execution.
