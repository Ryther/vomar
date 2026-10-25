from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]


def test_deliberate_bluetooth_expires_but_fault_or_partial_recovery_does_not(tmp_path):
    executable = tmp_path / "recovery_session"
    subprocess.run([
        "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-fsanitize=undefined",
        "-I", str(ROOT / "firmware/recovery/src"),
        "-I", str(ROOT / "firmware/src"),
        str(ROOT / "firmware/recovery/src/recovery_session.c"),
        str(Path(__file__).with_name("recovery_session_test.c")),
        "-o", str(executable),
    ], check=True)
    subprocess.run([str(executable)], check=True)
