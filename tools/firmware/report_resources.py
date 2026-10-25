#!/usr/bin/env python3
"""Produce a stable flash/RAM reserve report from a Zephyr ELF."""

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ResourceUsage:
    flash_used: int
    flash_capacity: int
    ram_used: int
    ram_capacity: int


def parse_size_output(output: str, flash_capacity: int, ram_capacity: int) -> ResourceUsage:
    fields = output.strip().splitlines()[-1].split()
    if len(fields) < 3:
        raise ValueError("unexpected size output")
    text, data, bss = map(int, fields[:3])
    return ResourceUsage(text + data, flash_capacity, data + bss, ram_capacity)


def read_elf_usage(elf: Path, flash_capacity: int, ram_capacity: int) -> ResourceUsage:
    result = subprocess.run(["arm-none-eabi-size", str(elf)], check=True,
                            text=True, capture_output=True)
    return parse_size_output(result.stdout, flash_capacity, ram_capacity)


def markdown_report(usage: ResourceUsage, flash_baseline: int, ram_baseline: int) -> str:
    rows = []
    for name, used, capacity, baseline in (
        ("Flash", usage.flash_used, usage.flash_capacity, flash_baseline),
        ("RAM", usage.ram_used, usage.ram_capacity, ram_baseline),
    ):
        free = capacity - used
        percent = used * 100 / capacity
        delta = used - baseline
        result = "PASS" if used * 100 <= capacity * 85 else "FAIL"
        rows.append(f"| {name} | {used} | {capacity} | {free} | {percent:.2f}% | {delta:+d} | {result} |")
    return "\n".join([
        "| Resource | Used | Capacity | Free | Used % | Baseline delta | Gate |",
        "|---|---:|---:|---:|---:|---:|:---:|", *rows,
    ]) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--flash-capacity", type=int, default=466432)
    parser.add_argument("--ram-capacity", type=int, default=262144)
    parser.add_argument("--flash-baseline", type=int, default=381808)
    parser.add_argument("--ram-baseline", type=int, default=58804)
    args = parser.parse_args()
    usage = read_elf_usage(args.elf, args.flash_capacity, args.ram_capacity)
    print(markdown_report(usage, args.flash_baseline, args.ram_baseline), end="")
    if usage.flash_used * 100 > usage.flash_capacity * 85 or usage.ram_used * 100 > usage.ram_capacity * 85:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
