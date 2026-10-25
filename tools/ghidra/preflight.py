#!/usr/bin/env python3
"""Validate immutable firmware evidence before running Ghidra."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys


SRAM_START = 0x20000000
SRAM_END = 0x20040000


def load_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    targets = manifest.get("targets")
    if not isinstance(targets, dict) or not targets:
        raise ValueError("manifest targets must be a non-empty named mapping")
    return manifest


def _integer(value, field: str) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as error:
            raise ValueError(f"invalid {field}: {value}") from error
    raise ValueError(f"invalid {field}: expected integer or numeric string")


def validate_target(repo: Path, target: dict) -> dict:
    source_relative = Path(target["source_path"])
    if source_relative.is_absolute() or ".." in source_relative.parts:
        raise ValueError("source_path must be repository-relative")
    source = repo / source_relative
    if not source.is_file():
        raise ValueError(f"firmware source does not exist: {source_relative.as_posix()}")

    data = source.read_bytes()
    expected_size = _integer(target["size"], "size")
    if len(data) != expected_size:
        raise ValueError(f"size mismatch: expected {expected_size}, found {len(data)}")

    digest = hashlib.sha256(data).hexdigest()
    expected_digest = str(target["sha256"]).lower()
    if digest != expected_digest:
        raise ValueError(f"SHA-256 mismatch: expected {expected_digest}, found {digest}")
    if len(data) < 8:
        raise ValueError("firmware is too short to contain an ARM vector table")

    initial_sp, reset_vector = struct.unpack_from("<II", data, 0)
    if not SRAM_START <= initial_sp <= SRAM_END:
        raise ValueError(f"initial stack pointer 0x{initial_sp:08x} is outside nRF52840 SRAM")
    if reset_vector & 1 == 0:
        raise ValueError(f"reset vector 0x{reset_vector:08x} has no Thumb bit")

    image_base = _integer(target["image_base"], "image_base")
    reset_handler = reset_vector & ~1
    expected_handler = _integer(target["reset_handler"], "reset_handler")
    if reset_handler != expected_handler:
        raise ValueError(
            f"reset handler mismatch: expected 0x{expected_handler:08x}, "
            f"found 0x{reset_handler:08x}"
        )
    if not image_base <= reset_handler < image_base + len(data):
        raise ValueError(f"reset handler 0x{reset_handler:08x} is outside loaded image")

    return {
        "name": str(target["name"]),
        "source_path": source_relative.as_posix(),
        "sha256": digest,
        "size": len(data),
        "image_base": image_base,
        "initial_sp": initial_sp,
        "reset_vector": reset_vector,
        "reset_handler": reset_handler,
    }


def _json_ready(result: dict) -> dict:
    output = result.copy()
    for field in ("image_base", "initial_sp", "reset_vector", "reset_handler"):
        output[field] = f"0x{result[field]:08x}"
    output["analyze_headless"] = shutil.which("analyzeHeadless")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=("mesh", "zigbee"))
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[2]
    manifest_path = Path(__file__).with_name("firmware_manifest.json")
    try:
        manifest = load_manifest(manifest_path)
        result = validate_target(repo, manifest["targets"][args.target])
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"preflight: {error}", file=sys.stderr)
        return 1

    ready = _json_ready(result)
    if args.as_json:
        print(json.dumps(ready, sort_keys=True))
    else:
        print(f"{args.target}: evidence validated ({ready['sha256']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
