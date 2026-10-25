#!/usr/bin/env python3
import argparse
import re
import struct
import subprocess
import sys
from pathlib import Path


def parse_partitions(path: Path) -> list[tuple[str, int, int]]:
    current = None
    values: dict[str, dict[str, str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([a-zA-Z0-9_]+):", line)
        if match:
            current = match.group(1)
            values[current] = {}
        elif current and (field := re.fullmatch(r"  (address|size): (0x[0-9a-fA-F]+)", line)):
            values[current][field.group(1)] = field.group(2)
        elif current and re.fullmatch(r"  span:.*", line):
            values[current]["virtual"] = "true"
    return [
        (name, int(fields["address"], 16), int(fields["size"], 16))
        for name, fields in values.items()
        if "address" in fields and "size" in fields and "virtual" not in fields
    ]


def parse_source_version(path: Path) -> tuple[int, int, int, int]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(
            r"(VERSION_MAJOR|VERSION_MINOR|PATCHLEVEL|VERSION_TWEAK)\s*=\s*(\d+)",
            line,
        )
        if match:
            values[match.group(1)] = int(match.group(2))
    required = ("VERSION_MAJOR", "VERSION_MINOR", "PATCHLEVEL", "VERSION_TWEAK")
    if any(name not in values for name in required):
        raise ValueError("incomplete source VERSION")
    return tuple(values[name] for name in required)


def parse_mcuboot_image_version(path: Path) -> tuple[int, int, int, int]:
    header = path.read_bytes()[:32]
    if len(header) < 32:
        raise ValueError("MCUboot image header is truncated")
    magic, _, _, _, _, _, major, minor, revision, build = struct.unpack(
        "<IIHHIIBBHI", header[:28]
    )
    if magic != 0x96F3B83D:
        raise ValueError("invalid MCUboot image magic")
    return major, minor, revision, build


def validate_resource_budget(
    flash_used: int,
    ram_used: int,
    flash_capacity: int,
    ram_capacity: int,
) -> None:
    """Require at least fifteen percent free flash and static RAM."""
    if flash_used * 100 > flash_capacity * 85:
        raise ValueError(
            f"flash budget exceeded: {flash_used}/{flash_capacity} bytes used"
        )
    if ram_used * 100 > ram_capacity * 85:
        raise ValueError(f"RAM budget exceeded: {ram_used}/{ram_capacity} bytes used")


def parse_static_ram_usage(path: Path) -> int:
    result = subprocess.run(
        ["arm-none-eabi-size", str(path)],
        check=True,
        text=True,
        capture_output=True,
    )
    fields = result.stdout.splitlines()[-1].split()
    if len(fields) < 4:
        raise ValueError("unexpected arm-none-eabi-size output")
    return int(fields[1]) + int(fields[2])


def validate_source(source: Path) -> None:
    sysbuild = (source / "sysbuild.conf").read_text(encoding="utf-8")
    required = (
        "SB_CONFIG_BOOTLOADER_MCUBOOT=y",
        "SB_CONFIG_BOOT_SIGNATURE_TYPE_ECDSA_P256=y",
        "keys/dev-private.pem",
    )
    for setting in required:
        if setting not in sysbuild:
            raise ValueError(f"missing sysbuild signing setting: {setting}")
    partitions = sorted(parse_partitions(source / "pm_static.yml"), key=lambda item: item[1])
    if not partitions:
        raise ValueError("no physical partitions found")
    previous_name, _, previous_size = partitions[0]
    previous_end = partitions[0][1] + previous_size
    for name, address, size in partitions[1:]:
        if address < previous_end:
            raise ValueError(f"partition overlap: {previous_name} and {name}")
        previous_name, previous_end = name, address + size
    if partitions[-1][1] + partitions[-1][2] > 0x100000:
        raise ValueError("partitions exceed nRF52840 flash")
    names = {name for name, _, _ in partitions}
    for required_name in (
        "mcuboot",
        "mcuboot_pad",
        "app",
        "mcuboot_secondary",
        "settings_storage",
        "zboss_nvram",
        "zboss_product_config",
    ):
        if required_name not in names:
            raise ValueError(f"missing partition: {required_name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path)
    args = parser.parse_args()
    try:
        validate_source(args.source)
        if args.build_dir is not None:
            required = (
                "firmware/zephyr/.config",
                "firmware/zephyr/zephyr.elf",
                "mcuboot/zephyr/.config",
                "partitions.yml",
                "firmware/zephyr/zephyr.signed.bin",
                "dfu_application.zip",
                "merged.hex",
            )
            missing = [name for name in required if not (args.build_dir / name).is_file()]
            if missing:
                raise ValueError("missing generated build artifacts: " + ", ".join(missing))
            source_version = parse_source_version(args.source / "VERSION")
            image_version = parse_mcuboot_image_version(
                args.build_dir / "firmware/zephyr/zephyr.signed.bin"
            )
            if image_version != source_version:
                raise ValueError(
                    f"image version {image_version} does not match source VERSION {source_version}"
                )
            partition_sizes = {
                name: size for name, _, size in parse_partitions(args.source / "pm_static.yml")
            }
            signed_image = args.build_dir / "firmware/zephyr/zephyr.signed.bin"
            validate_resource_budget(
                signed_image.stat().st_size,
                parse_static_ram_usage(args.build_dir / "firmware/zephyr/zephyr.elf"),
                partition_sizes["app"],
                0x40000,
            )
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
    print("source contract: valid")
    if args.build_dir is not None:
        print("generated artifacts: present")
        print("resource budget: at least 15% flash and static RAM reserved")


if __name__ == "__main__":
    main()
