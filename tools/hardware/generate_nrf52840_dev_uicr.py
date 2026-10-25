#!/usr/bin/env python3
"""Generate the development-only nRF52840 APPROTECT UICR Intel HEX."""

import argparse
from pathlib import Path


APPROTECT_ADDRESS = 0x10001208
APPROTECT_DEVELOPMENT_VALUE = 0x0000005A


def intel_hex_record(address: int, record_type: int, data: bytes) -> str:
    body = bytes([len(data)]) + address.to_bytes(2, "big") + bytes([record_type]) + data
    checksum = (-sum(body)) & 0xFF
    return f":{(body + bytes([checksum])).hex().upper()}"


def generate_hex() -> str:
    upper_address = APPROTECT_ADDRESS >> 16
    lower_address = APPROTECT_ADDRESS & 0xFFFF
    records = [
        intel_hex_record(0, 0x04, upper_address.to_bytes(2, "big")),
        intel_hex_record(
            lower_address,
            0x00,
            APPROTECT_DEVELOPMENT_VALUE.to_bytes(4, "little"),
        ),
        intel_hex_record(0, 0x01, b""),
    ]
    return "\n".join(records) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(generate_hex(), encoding="ascii")


if __name__ == "__main__":
    main()
