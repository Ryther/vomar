"""Local overrides inherit the canonical image without importing arbitrary state."""

import copy
import json

import pytest


def base_config():
    return {
        "name": "Vomar development",
        "build": {"dockerfile": "Dockerfile", "context": ".."},
        "mounts": ["source=vimar-30805-codex,target=/home/vscode/.codex,type=volume"],
        "features": {"pinned-feature@sha256:fixture": {"version": "fixed"}},
        "containerEnv": {"ANDROID_HOME": "/home/vscode/.cache/vomar/android"},
        "runArgs": [
            "--volume=${localEnv:VOMAR_USB_DEVICE:vomar-no-host-usb}:/dev/bus/usb",
            "--volume=${localEnv:VOMAR_DBUS_SOURCE:vomar-no-host-dbus}:/run/dbus:ro",
            "--device=${localEnv:VOMAR_KVM_DEVICE:/dev/null}",
            "--group-add=${localEnv:VOMAR_KVM_GID:65534}",
            "--group-add=plugdev",
        ],
    }


def test_local_profile_keeps_current_features_and_only_inherits_known_host_connections(
    tmp_path,
):
    from tools.dev.local_container import derive

    base = base_config()
    original = copy.deepcopy(base)
    old = {
        "HostConfig": {
            "CapAdd": ["CAP_SYS_PTRACE"],
            "SecurityOpt": ["seccomp=unconfined"],
        },
        "Config": {
            "Env": ["DISPLAY=:0", "SECRET_TOKEN=never-copy"],
            "Labels": {
                "devcontainer.metadata": json.dumps(
                    [
                        {
                            "customizations": {
                                "vscode": {
                                    "extensions": ["vendor.fixture"],
                                    "settings": {
                                        "telemetry.telemetryLevel": "off",
                                        "private.setting": "not-copied",
                                    },
                                }
                            },
                            "postAttachCommand": "do-not-inherit",
                        }
                    ]
                )
            },
        },
        "Mounts": [
            {
                "Type": "bind",
                "Source": "/host/.ssh",
                "Destination": "/home/vscode/.ssh",
                "RW": True,
            },
            {
                "Type": "bind",
                "Source": "/dev/bus/usb",
                "Destination": "/dev/bus/usb",
                "RW": True,
            },
            {
                "Type": "bind",
                "Source": "/run/dbus/system_bus_socket",
                "Destination": "/run/dbus/system_bus_socket",
                "RW": True,
            },
            {
                "Type": "bind",
                "Source": "/host/.docker.xauth",
                "Destination": "/home/vscode/.Xauthority",
                "RW": True,
            },
            {
                "Type": "bind",
                "Source": "/tmp/.X11-unix",
                "Destination": "/tmp/.X11-unix",
                "RW": True,
            },
            {
                "Type": "bind",
                "Source": "/host/private",
                "Destination": "/run/private",
                "RW": True,
            },
            {
                "Type": "volume",
                "Name": "old-codex",
                "Destination": "/home/vscode/.codex",
                "RW": True,
            },
        ],
    }
    result = derive(base, old, tmp_path, kvm=True, kvm_gid=990)
    assert base == original
    assert result["features"] == base["features"]
    assert "--cap-add=SYS_PTRACE" in result["runArgs"]
    assert not any("seccomp=unconfined" in a for a in result["runArgs"])
    assert result["customizations"]["vscode"]["extensions"] == ["vendor.fixture"]
    assert result["customizations"]["vscode"]["settings"] == {
        "telemetry.telemetryLevel": "off"
    }
    assert "postAttachCommand" not in result
    assert base["mounts"][0] in result["mounts"]
    assert not any("old-codex" in m or "/host/private" in m for m in result["mounts"])
    assert (
        "source=/host/.ssh,target=/home/vscode/.ssh,type=bind,readonly"
        in result["mounts"]
    )
    assert result["containerEnv"]["DISPLAY"] == ":0"
    assert "SECRET_TOKEN" not in result["containerEnv"]
    assert result["containerEnv"]["XAUTHORITY"] == "/home/vscode/.Xauthority"
    assert not any(
        "VOMAR_USB_DEVICE" in a or "VOMAR_DBUS_SOURCE" in a or "VOMAR_KVM_DEVICE" in a
        for a in result["runArgs"]
    )
    assert "--device=/dev/kvm" in result["runArgs"]
    assert "--group-add=990" in result["runArgs"]
    assert not any("VOMAR_KVM_GID" in a for a in result["runArgs"])
    with pytest.raises(ValueError, match="group ID"):
        derive(base, old, tmp_path, kvm=True)
    assert "--device-cgroup-rule=c 189:* rmw" in result["runArgs"]
    assert result["build"]["dockerfile"] == str(tmp_path / ".devcontainer/Dockerfile")
    assert result["workspaceFolder"] == "${localWorkspaceFolder}"


def test_sdk_and_ghidra_paths_are_explicit_existing_tools_without_changing_firmware_graph(
    tmp_path,
):
    from tools.dev.local_container import derive

    sdk = tmp_path / "work/android-sdk"
    (sdk / "platform-tools").mkdir(parents=True)
    (sdk / "platform-tools/adb").touch()
    ghidra = tmp_path / "work/tools/ghidra"
    (ghidra / "support").mkdir(parents=True)
    (ghidra / "support/analyzeHeadless").touch()
    result = derive(
        base_config(),
        {"Config": {}, "Mounts": []},
        tmp_path,
        android_sdk=sdk,
        ghidra_home=ghidra,
        ghidra_compat_path="/opt/ghidra-12.1.2",
    )
    assert (
        result["containerEnv"]["ANDROID_HOME"]
        == "${containerWorkspaceFolder}/work/android-sdk"
    )
    assert (
        result["containerEnv"]["ANDROID_SDK_ROOT"]
        == result["containerEnv"]["ANDROID_HOME"]
    )
    assert (
        result["containerEnv"]["GHIDRA_HOME"]
        == "${containerWorkspaceFolder}/work/tools/ghidra"
    )
    assert "VIMAR_NCS_WORKSPACE" not in result["containerEnv"]
    assert (
        f"source={ghidra},target=/opt/ghidra-12.1.2,type=bind,readonly"
        in result["mounts"]
    )
    with pytest.raises(ValueError, match="compatibility"):
        derive(
            base_config(),
            {},
            tmp_path,
            ghidra_home=ghidra,
            ghidra_compat_path="/home/vscode/.codex",
        )
    assert "${containerEnv:PATH}" in result["remoteEnv"]["PATH"]
    assert "platform-tools" in result["remoteEnv"]["PATH"]
    with pytest.raises(ValueError, match="SDK"):
        derive(base_config(), {}, tmp_path, android_sdk=tmp_path / "missing")


def test_existing_profile_needs_explicit_replace_and_no_auth_data_is_read(tmp_path):
    from tools.dev.local_container import write_profile

    target = tmp_path / "local/devcontainer.json"
    target.parent.mkdir()
    target.write_text("existing")
    with pytest.raises(FileExistsError):
        write_profile({"name": "new"}, target)
    assert target.read_text() == "existing"
    write_profile({"name": "new"}, target, replace=True)
    assert json.loads(target.read_text()) == {"name": "new"}
    assert target.with_suffix(".json.previous").read_text() == "existing"


def test_existing_zephyr_toolchain_retains_legacy_path_without_retargeting_ncs(
    tmp_path,
):
    from tools.dev.local_container import derive

    sdk = tmp_path / "work/tools/zephyr-sdk-1.0.1"
    compiler = sdk / "gnu/arm-zephyr-eabi/bin/arm-zephyr-eabi-gcc"
    compiler.parent.mkdir(parents=True)
    compiler.touch()
    (sdk / "sdk_version").write_text("1.0.1\n")
    base = base_config()
    base["containerEnv"]["VIMAR_NCS_WORKSPACE"] = "/canonical/ncs"
    result = derive(base, {}, tmp_path, zephyr_sdk=sdk)
    assert (
        result["containerEnv"]["ZEPHYR_SDK_INSTALL_DIR"]
        == "${containerWorkspaceFolder}/work/tools/zephyr-sdk-1.0.1"
    )
    assert result["containerEnv"]["VIMAR_NCS_WORKSPACE"] == "/canonical/ncs"
    assert (
        f"source={sdk},target=/opt/zephyr-sdk-1.0.1,type=bind,readonly"
        in result["mounts"]
    )
    (sdk / "sdk_version").write_text("../../invalid")
    with pytest.raises(ValueError, match="version"):
        derive(base, {}, tmp_path, zephyr_sdk=sdk)


def test_cli_help_does_not_require_docker_or_format_stat_percent_as_a_placeholder():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "tools.dev.local_container", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "stat -c %g /dev/kvm" in result.stdout
    assert "--inherit-from-container" in result.stdout
