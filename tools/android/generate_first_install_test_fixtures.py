"""Create synthetic first-install inputs for instrumented Gradle JVM tests.

The existing independent Python fixture builder signs disposable packages with
ephemeral keys. No acquired image, credential, target or service is accessed.
Only public keys and synthetic packages are written.
"""
from __future__ import annotations

import argparse
import hashlib
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def generate(output: Path) -> None:
    fixture = runpy.run_path(str(Path(__file__).parent / "first_install_contract/tests/test_first_install_contract.py"))
    output.mkdir(parents=True, exist_ok=True)
    for name, options in (
        ("candidate", {}),
        ("watchdog", {"watchdog_handoff": "paused-reset-before-main-v1"}),
    ):
        raw, public, _, _ = fixture["common_fixture"](candidate=True, **options)
        (output / f"{name}.zip").write_bytes(raw)
        (output / f"{name}-public.der").write_bytes(public)
    regions, manifest = fixture["original_fixture"]()
    (output / "original.zip").write_bytes(fixture["archive"](regions, manifest))
    regions["flash.bin"] = regions["flash.bin"][:0xef000] + b"\xff" * 0x11000
    manifest["regions"][0]["sha256"] = hashlib.sha256(regions["flash.bin"]).hexdigest()
    (output / "original-erased-tail.zip").write_bytes(fixture["archive"](regions, manifest))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    generate(parser.parse_args().output)
