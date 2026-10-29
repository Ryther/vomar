# Development

Open `.devcontainer/devcontainer.json` in Dev Containers. This is the canonical
development configuration: firmware, Android, desktop, hardware and research
work use the same image. A retained local workstation file must be regenerated
from this configuration after changes; an old copy can silently omit new tools,
mounts or Features. The local compatibility helper below refreshes it.

The Ubuntu image pins Python 3.13.12, Node 24 and assistant packages; npm verifies
package integrity. Java 21 runs Gradle 9.6.0, AGP 9.4.1 and Kotlin 2.4.21;
Java 17 remains the bytecode target. Git and the OpenSSH client, Docker CLI/Buildx,
GitHub CLI, Codex, OpenCode, Claude and the Linux GUI runtime are available.
Bluetooth/USB clients, GDB, sigrok/PulseView and a full Java 21 GUI runtime are
also installed. Startup checks Docker, gh and `ssh -V` without logging in,
contacting an assistant or opening hardware.

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
opening VS Code. Dev Containers can forward the agent; the public configuration
does not mount a private-key directory. When explicitly inheriting an older local
workstation, the compatibility helper can retain its SSH directory read-only;
it does not read or copy keys. `ssh -V` checks the client, while
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
licenses interactively, then install android-37.0 and build-tools 36.0.0 as printed
by the helper. Firmware setup uses the 55-project frozen public west manifest,
a separate Python environment and only the ARM Zephyr SDK toolchain. Research
setup installs gdb-multiarch, binwalk and wireshark-common; install a reviewed
Ghidra release separately. These steps do not rebuild/switch containers, open
hardware or import proprietary evidence. Nordic binary-stack licenses apply.
An emulator is added by CI for synthetic Android UI coverage, not installed by
default in the development image.

Android CI selects `CiUiSuite` as one instrumentation class. The pinned test
engine truncates comma-separated class arguments, so the suite groups the eight
synthetic UI, persistence and connection journeys. JUnit verification requires
an executed, non-skipped testcase from every expected class before coverage is
accepted. Emulator tests use synthetic transports and do not qualify devices.

Android Gradle tests generate signed synthetic fixtures with Python using the
locked `pytest` and `cryptography` packages in `requirements-dev.lock`. Workspace
bootstrap installs these packages; set `VOMAR_PYTHON` to that environment's Python
when invoking Gradle from another shell. Device coverage uses an isolated API 35
emulator and the synthetic first-install UI/adapter tests. Ordinary unit tests
and `jacocoDebugReport` never start an emulator or access physical hardware.

## Android checks and local builds

Use the pinned container and complete `python tools/dev/bootstrap.py workspace`
and `python tools/dev/bootstrap.py android` from the repository root. Accept the
SDK licenses and install `platforms;android-37.0` and `build-tools;36.0.0` as
printed by setup. Java 21 runs Gradle; Java 17 remains the bytecode target.
Set `ANDROID_HOME` to that prepared SDK and `VOMAR_PYTHON` to the locked workspace
Python, which generates signed synthetic test fixtures. No attached device is
needed for the contributor checks below.

From `apps/android-updater`, with the pinned dependencies available, run:

```sh
export VOMAR_PYTHON=/home/vscode/.cache/vomar/dev-venv/bin/python
./gradlew --dependency-verification=strict :core:test :core:jacocoTestReport :app:testDebugUnitTest :app:jacocoDebugReport :app:lint :app:verifyReleaseObfuscation :app:writeRuntimeInventory :app:assembleRelease
```

Gradle uses the checked-in dependency locks and strict artifact verification.
Add `--offline` only after populating the pinned cache; a clean checkout cannot
resolve uncached dependencies offline. Do not regenerate locks or verification
metadata merely to bypass a failure. The unsigned contributor APK is
`app/build/outputs/apk/release/app-release-unsigned.apk`, relative to this working
directory. Runtime inventory is `app/build/reports/dependencies/android-runtime.json`;
core/app coverage reports are under their respective `build/reports/jacoco` trees.

Release builds use R8 obfuscation and resource shrinking.
`verifyReleaseObfuscation` depends on `assembleRelease` and inspects the actual
unsigned APK and `app/build/outputs/mapping/release/mapping.txt` for renamed
project classes. Retain that mapping with the exact APK and its revision/hash;
a mapping from a later rebuild cannot reliably decode its stack traces. Debug
JVM tests and coverage do not execute optimized release code. Optimized-runtime
checks must run the corresponding release APK, while synthetic emulator
instrumentation and physical Bluetooth/USB/power-cut qualification remain
separate checks. The command above starts neither an emulator nor hardware.

### Maintainer local APK helper and signing continuity

**Official updates require the existing Android signing identity.** Before using
this maintainer helper for an official update, ensure the existing private
`work/private/android-updater/signing.jks` and `signing-password.txt` are present
through the authorized private custody process. The helper creates a new local
identity if **both** files are absent, and refuses an incomplete pair. A clean
checkout therefore does not reproduce the shipped signer. A newly created local
identity is only for disposable local builds; it cannot update the official app
in place. Never regenerate or replace official signing material to fix a build
or signer error, and never uninstall an owner's app to bypass continuity.
Unsigned contributor checks above need no private Android signing identity.

For a local maintainer build, return to the repository root. The helper uses
`ANDROID_HOME` (default `work/android-sdk`), Java and the prepared offline cache;
its supported invocation is:

```sh
python tools/android/build_updater.py --output experiments/android-updater/builds/local-review
```

Use a new output directory inside the repository, outside `inputs/`; an existing
directory is refused. Omitting `--output` creates a timestamped directory under
`experiments/android-updater/builds/APP_VERSION/`. The helper runs strict offline
core/app tests, lint and release-obfuscation verification/assembly, aligns and
signs the APK, then audits it before publishing the local
`vimar-updater-APP_VERSION.apk`. It writes logs, `SHA256SUMS` and `report.json`;
it builds no firmware bundle and runs no instrumentation or physical checks.
Retain the matching Gradle R8 mapping separately; the helper does not copy it to
the output directory. It does not run the coverage/runtime-inventory tasks above.


Android signing is separate from firmware signing. The APK audit compares its
firmware public DER trust anchor with `firmware/keys/dev-public.pem`, checks
release identity/manifest settings and notices, and rejects debug signers,
synthetic fixture anchors, unexpected firmware/private-key material and private
PEM markers. These bounded audits are not an exhaustive secret scan and do not
establish that a newly created local Android signer is the official signer.
Changing the download source never changes firmware trust. Preserve the existing
public trust identity; runtime license text is in the APK asset
`third_party_notices.txt` and [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## Isolated native desktop runtime

The desktop native jobs use CPython 3.13.18 and OpenSSL 3.5.9 from the whole
Astral Python Build Standalone 20261026 runtime, selected by exact platform,
archive SHA256 and source provenance in `tools/dev/desktop-runtimes.json`.
This changes neither the container's Python 3.13.12 nor the independent firmware
SDK environment. Do not replace individual OpenSSL DLLs or combine runtime trees.

For a native rebuild on the matching OS/architecture, use a new private output
directory and Bash (Git Bash on Windows):

```sh
python - <<'PY'
from pathlib import Path
import shutil, subprocess
from tools.dev.desktop_runtime import bootstrap
env = bootstrap(Path('_test/desktop-runtime'))
python = shutil.which('python', path=env['PATH'])
for arguments in [
    ['-m', 'pip', 'install', '--require-hashes', '-r', 'requirements-desktop.lock'],
    ['-m', 'pip', 'install', '--no-deps', '.'],
    ['-m', 'tools.release.package_desktop', '--output', '_test/native'],
]:
    subprocess.run([python, *arguments], env=env, check=True)
PY
```

The bootstrap checks the complete compressed archive before bounded extraction,
verifies the selected interpreter and OpenSSL before creating its own venv, and
clears inherited Python/loader overrides for child processes. It refuses an
existing destination. CI exports this environment only to subsequent native
desktop job steps. No SDK/global environment or container is replaced.

`vomar --runtime-info` reads runtime identity and default CA-store metadata;
it opens no application state or network connection. The explicit
`--runtime-info --tls-self-test` adds a bounded disposable loopback TLS test with
fresh synthetic certificates. Frozen native builds require both trust success
and untrusted-certificate rejection, plus observed default CA-store entries.
OpenSSL may load hashed CA directories lazily, so zero cached CA certificates
alone is not an empty trust store. User `SSL_CERT_FILE`/`SSL_CERT_DIR` choices are
retained; no global certificate override is installed. These checks do not
qualify Bluetooth, USB, a broker or physical firmware behavior.

## Run and inspect the desktop GUI

Install `requirements-desktop.lock` in a disposable Python 3.13 environment and
install this project with `--no-deps`; keep this environment separate from the
firmware SDK. From the repository root, use synthetic private state:

```sh
PYTHONPATH="$PWD/apps/desktop-updater/src" python -m vomar_updater.gui.app --state "$PWD/_test/desktop-manual-state"
```

The development image includes Qt's X11 runtime dependencies. The default
container does not forward a host display. Interactive use needs a deliberately
mounted host X11 socket, matching `DISPLAY` and host display authorization;
setting `DISPLAY` alone is insufficient. With the socket mounted and container
UID matching the host desktop user's UID, grant access in a **host** terminal:

```sh
xhost +SI:localuser:"$(id -un)"
```

After the GUI session, revoke that grant on the host:

```sh
xhost -SI:localuser:"$(id -un)"
```

For a bounded startup smoke check without a host display:

```sh
QT_QPA_PLATFORM=xcb PYTHONPATH="$PWD/apps/desktop-updater/src" xvfb-run -a python -m vomar_updater.gui.app --state "$PWD/_test/desktop-smoke-state" --smoke-test
```

A missing Qt library differs from display authorization failure: inspect native
library resolution (for example with `ldd`) before changing display permissions.
Use `QT_QPA_PLATFORM=offscreen` for the synthetic Qt test suite. Smoke/offscreen
checks do not establish host interaction, native dialogs or BLE/USB behavior.
See [UX evidence](ux-evidence.md) for the required review journeys.

## Optional Linux bench connections

Use the same configuration. To expose Linux USB and the system D-Bus socket,
set the following in the host shell **before the first container creation**, and
open VS Code from that shell:

```sh
export VOMAR_USB_DEVICE=/dev/bus/usb
export VOMAR_DBUS_SOURCE=/run/dbus
export VOMAR_KVM_DEVICE=/dev/kvm  # only if the host provides KVM
export VOMAR_KVM_GID="$(stat -c %g /dev/kvm)"  # grant the non-root container user access
code .
```

Review host USB/plugdev and D-Bus access first. Without these variables, the
container uses empty private USB/D-Bus volumes and maps only `/dev/null` for
virtualization, so CI and ordinary development do not require attached hardware or host services. Changing
host mounts later requires recreating this same configuration after saving work;
it never requires another profile. The USB bind and major-189 cgroup rule also cover devices reconnected after
startup; mapping only the original USB nodes misses hotplug. Access does not
authorize programming, erasure, scanning at startup or recovery. Tests use synthetic targets only.

## Repair a retained local workstation configuration

First inspect the running container's `devcontainer.config_file` label. Editing
`.devcontainer/devcontainer.json` cannot change a container launched from an older
ignored `.devcontainer/local-preserve-codex/devcontainer.json` copy.

To refresh that retained local file from the current canonical configuration and
inherit the known workstation connections from an existing container:

```sh
python tools/dev/local_container.py --inherit-from-container previous-container --replace
```

The helper reads Docker metadata only. It keeps the canonical image, pinned
Features, persistent SDK/Gradle/GitHub/Codex volumes and lifecycle commands;
it imports only known USB/D-Bus/X11/SSH mounts, selected editor preferences and
the existing debugger capability. It never starts/stops a container or imports
arbitrary environment variables, credentials or old startup scripts. The previous
local file is retained as `devcontainer.json.previous`. The generated file is
ignored and stays machine-specific.

Optional arguments select existing workspace tools and Linux KVM:

```sh
python tools/dev/local_container.py --inherit-from-container previous-container --replace \
  --android-sdk "$PWD/work/android-sdk" --ghidra-home "$PWD/work/tools/ghidra-12.1.2" \
  --zephyr-sdk "$PWD/work/tools/zephyr-sdk-1.0.1" \
  --ghidra-compat-path /opt/ghidra-12.1.2 --kvm --kvm-gid HOST_KVM_GROUP_ID
```

Replace `HOST_KVM_GROUP_ID` with the numeric result of `stat -c %g /dev/kvm`
on the host. Omit KVM options if the host does not provide it.
Omit paths for tools not already installed. Ghidra must come from a reviewed
installation; the helper neither downloads it nor copies an old installation.
The optional compatibility mount preserves an absolute Ghidra path already used
by REA without editing assistant configuration. An SDK environment variable alone
does not install an SDK. The inherited Android SDK is added to the editor's PATH; firmware graph variables retain their canonical
pinned-cache destinations. Do not redirect them to an older, different west graph.
An explicitly selected existing Zephyr SDK retains its compiler and `/opt` path
without registering a different NCS source graph. A Python compatibility alias preserves existing 3.13 virtualenv interpreter paths
at `/usr/local/python/current`; it does not update their packages or SDK revision.

After saving active work, rebuild/reopen the **generated local configuration**
through Dev Containers. The shared `vimar-30805-codex` volume remains in place.
Existing running containers do not acquire new mounts or packages when JSON is
edited. Do not delete session volumes or copy authentication into the repository.

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

Host C coverage compiles all translation units with coverage enabled, then
uses GCC filename filtering to retain durable firmware sources, including code
included by a synthetic harness. gcovr selects product firmware files and
excludes disposable harnesses and synthetic headers from the report. GCC maps
and executed profiles must still match exactly, and gcovr errors remain fatal. Run the actual native suites
and produce XML with:

```sh
python -m tools.release.c_coverage --output _test/c-coverage
```

Use a new output directory for each run so older execution profiles cannot
stand in for the current candidate's execution.
