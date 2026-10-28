"""Derive an ignored Linux workstation config from the current public devcontainer."""

from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BIND_TARGETS = {
    "/home/vscode/.ssh",
    "/home/vscode/.Xauthority",
    "/tmp/.X11-unix",
    "/dev/bus/usb",
    "/run/dbus/system_bus_socket",
    "/etc/localtime",
}
VOLUME_TARGETS = {
    "/commandhistory",
    "/home/vscode/.cache",
    "/home/vscode/.vscode-server/extensions",
}
READ_ONLY = {
    "/home/vscode/.ssh",
    "/home/vscode/.Xauthority",
    "/tmp/.X11-unix",
    "/etc/localtime",
}


def derive(
    base,
    old,
    root,
    *,
    kvm=False,
    kvm_gid=None,
    android_sdk=None,
    ghidra_home=None,
    ghidra_compat_path=None,
    zephyr_sdk=None,
):
    root = Path(root).resolve()
    result = copy.deepcopy(base)
    result["name"] = "Vomar development - local workstation"
    result["build"] = {
        "dockerfile": str(root / ".devcontainer/Dockerfile"),
        "context": str(root),
    }
    result["workspaceFolder"] = "${localWorkspaceFolder}"
    result["workspaceMount"] = (
        "source=${localWorkspaceFolder},target=${localWorkspaceFolder},type=bind"
    )
    mounts = result.setdefault("mounts", [])
    targets = set()
    for mount in old.get("Mounts", []):
        target = mount.get("Destination")
        kind = mount.get("Type")
        if kind == "bind" and target in BIND_TARGETS:
            source = mount["Source"]
        elif kind == "volume" and target in VOLUME_TARGETS:
            source = mount["Name"]
        else:
            continue
        if any(c in source for c in ",\n\r\x00"):
            raise ValueError("Unsupported host mount path")
        value = f"source={source},target={target},type={kind}"
        if target in READ_ONLY:
            value += ",readonly"
        mounts.append(value)
        targets.add(target)
    arguments = result.setdefault("runArgs", [])
    if "/dev/bus/usb" in targets:
        arguments[:] = [a for a in arguments if "VOMAR_USB_DEVICE" not in a]
        rule = "--device-cgroup-rule=c 189:* rmw"
        if rule not in arguments:
            arguments.append(rule)
    if "/run/dbus/system_bus_socket" in targets:
        arguments[:] = [a for a in arguments if "VOMAR_DBUS_SOURCE" not in a]
    if kvm:
        if not isinstance(kvm_gid, int) or not 0 <= kvm_gid <= 4294967294:
            raise ValueError(
                "KVM requires an explicit host device group ID (--kvm-gid)"
            )
        arguments[:] = [
            a
            for a in arguments
            if "VOMAR_KVM_DEVICE" not in a and "VOMAR_KVM_GID" not in a
        ]
        arguments.extend(["--device=/dev/kvm", f"--group-add={kvm_gid}"])
    if any(
        cap in {"SYS_PTRACE", "CAP_SYS_PTRACE"}
        for cap in old.get("HostConfig", {}).get("CapAdd", []) or []
    ):
        arguments.append("--cap-add=SYS_PTRACE")
    labels = old.get("Config", {}).get("Labels") or {}
    for item in json.loads(labels.get("devcontainer.metadata", "[]")):
        previous_editor = item.get("customizations", {}).get("vscode", {})
        if not previous_editor:
            continue
        editor = result.setdefault("customizations", {}).setdefault("vscode", {})
        extensions = editor.setdefault("extensions", [])
        for extension in previous_editor.get("extensions", []):
            if (
                isinstance(extension, str)
                and re.fullmatch(r"[A-Za-z0-9-]+\.[A-Za-z0-9_.-]+", extension)
                and extension not in extensions
            ):
                extensions.append(extension)
        for key, value in previous_editor.get("settings", {}).items():
            if key in {
                "telemetry.telemetryLevel",
                "explorer.compactFolders",
                "scm.compactFolders",
            }:
                editor.setdefault("settings", {})[key] = value
    env = result.setdefault("containerEnv", {})
    previous = dict(
        v.split("=", 1) for v in old.get("Config", {}).get("Env", []) if "=" in v
    )
    if "/tmp/.X11-unix" in targets:
        env["DISPLAY"] = previous.get("DISPLAY", ":0")
    if "/home/vscode/.Xauthority" in targets:
        env["XAUTHORITY"] = "/home/vscode/.Xauthority"
    paths = []

    def workspace_path(value, required, label):
        path = Path(value).resolve()
        if not path.is_relative_to(root) or not (path / required).is_file():
            raise ValueError(label + " must be an existing tool inside this workspace")
        return "${containerWorkspaceFolder}/" + path.relative_to(root).as_posix()

    if android_sdk:
        sdk = workspace_path(android_sdk, "platform-tools/adb", "Android SDK")
        env["ANDROID_HOME"] = sdk
        env["ANDROID_SDK_ROOT"] = sdk
        paths.extend([sdk + "/platform-tools", sdk + "/emulator"])
    if ghidra_home:
        ghidra = workspace_path(ghidra_home, "support/analyzeHeadless", "Ghidra")
        env["GHIDRA_HOME"] = ghidra
        paths.extend([ghidra, ghidra + "/support"])
        if ghidra_compat_path:
            if not re.fullmatch(
                r"/opt/ghidra(?:-[A-Za-z0-9_.-]+)?", ghidra_compat_path
            ):
                raise ValueError(
                    "Ghidra compatibility path must be /opt/ghidra or /opt/ghidra-VERSION"
                )
            mounts.append(
                f"source={Path(ghidra_home).resolve()},target={ghidra_compat_path},type=bind,readonly"
            )
    elif ghidra_compat_path:
        raise ValueError("Ghidra compatibility path requires --ghidra-home")
    if zephyr_sdk:
        sdk = workspace_path(
            zephyr_sdk, "gnu/arm-zephyr-eabi/bin/arm-zephyr-eabi-gcc", "Zephyr SDK"
        )
        version = (Path(zephyr_sdk).resolve() / "sdk_version").read_text().strip()
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
            raise ValueError("Zephyr SDK version must have three numeric components")
        env["ZEPHYR_SDK_INSTALL_DIR"] = sdk
        mounts.append(
            f"source={Path(zephyr_sdk).resolve()},target=/opt/zephyr-sdk-{version},type=bind,readonly"
        )
    if paths:
        result.setdefault("remoteEnv", {})["PATH"] = ":".join(
            paths + ["${containerEnv:PATH}"]
        )
    return result


def write_profile(config, target, *, replace=False):
    target = Path(target)
    if target.exists():
        if not replace:
            raise FileExistsError(
                "Local profile exists; use --replace to preserve a .previous copy and refresh it"
            )
        previous = target.with_suffix(".json.previous")
        # Keep the first pre-refresh copy; later refreshes do not destroy it.
        if not previous.exists():
            previous.write_bytes(target.read_bytes())
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.new")
    with temporary.open("x") as stream:
        json.dump(config, stream, indent=2)
        stream.write("\n")
    temporary.replace(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inherit-from-container",
        required=True,
        help="Read only known development mount metadata from this existing container",
    )
    parser.add_argument(
        "--kvm",
        action="store_true",
        help="Host must provide /dev/kvm; never enables privileged mode",
    )
    parser.add_argument(
        "--kvm-gid",
        type=int,
        help="Numeric group ID from stat -c %%g /dev/kvm on the host",
    )
    parser.add_argument("--android-sdk", type=Path)
    parser.add_argument("--ghidra-home", type=Path)
    parser.add_argument(
        "--zephyr-sdk",
        type=Path,
        help="Existing workspace Zephyr SDK; retains /opt compatibility without changing the NCS graph",
    )
    parser.add_argument(
        "--ghidra-compat-path",
        help="Optional read-only /opt/ghidra[-VERSION] mount for existing REA configuration",
    )
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    base = json.loads((ROOT / ".devcontainer/devcontainer.json").read_text())
    old = json.loads(
        subprocess.check_output(
            ["docker", "inspect", args.inherit_from_container], text=True
        )
    )[0]
    config = derive(
        base,
        old,
        ROOT,
        kvm=args.kvm,
        kvm_gid=args.kvm_gid,
        android_sdk=args.android_sdk,
        ghidra_home=args.ghidra_home,
        ghidra_compat_path=args.ghidra_compat_path,
        zephyr_sdk=args.zephyr_sdk,
    )
    output = ROOT / ".devcontainer/local-preserve-codex/devcontainer.json"
    write_profile(config, output, replace=args.replace)
    print(
        "Local profile refreshed from the current public configuration: " + str(output)
    )
    print(
        "Existing containers and authentication files were not changed. Rebuild/reopen this local config after saving active work."
    )


if __name__ == "__main__":
    main()
