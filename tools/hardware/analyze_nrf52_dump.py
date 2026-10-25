#!/usr/bin/env python3
"""Produce a sanitized, deterministic layout report for an nRF52 flash dump."""

import argparse
import hashlib
import json
import struct
from pathlib import Path


PAGE_SIZE = 4096
SOFTDEVICE_INFO_OFFSET = 0x3000
SOFTDEVICE_MAGIC = 0x51B1E5DB


def hex32(value):
    return f"0x{value:08x}"


def read_word(data, offset):
    if offset < 0 or offset + 4 > len(data):
        raise ValueError(f"word offset outside artifact: 0x{offset:x}")
    return struct.unpack_from("<I", data, offset)[0]


def decode_vector(data, offset):
    initial_sp = read_word(data, offset)
    reset_vector = read_word(data, offset + 4)
    plausible = (
        0x20000000 <= initial_sp <= 0x20040000
        and reset_vector & 1 == 1
        and (reset_vector & ~1) < len(data)
    )
    return {
        "offset": f"0x{offset:06x}",
        "initial_sp": hex32(initial_sp),
        "reset_vector": hex32(reset_vector),
        "plausible": plausible,
    }


def decode_softdevice(data):
    offset = SOFTDEVICE_INFO_OFFSET
    magic = read_word(data, offset + 4)
    if magic != SOFTDEVICE_MAGIC:
        return None
    return {
        "offset": f"0x{offset:06x}",
        "magic": hex32(magic),
        "application_start": hex32(read_word(data, offset + 8)),
        "fwid": f"0x{read_word(data, offset + 12) & 0xffff:04x}",
    }


def non_erased_runs(data):
    pages = []
    for offset in range(0, len(data), PAGE_SIZE):
        if any(byte != 0xFF for byte in data[offset : offset + PAGE_SIZE]):
            pages.append(offset)

    runs = []
    for offset in pages:
        if not runs or offset != runs[-1][1]:
            runs.append([offset, offset + PAGE_SIZE])
        else:
            runs[-1][1] += PAGE_SIZE
    return [
        {
            "start": f"0x{start:06x}",
            "end_exclusive": f"0x{min(end, len(data)):06x}",
            "pages": (min(end, len(data)) - start + PAGE_SIZE - 1) // PAGE_SIZE,
        }
        for start, end in runs
    ]


def decode_uicr(data):
    return {
        "bootloader_start": hex32(read_word(data, 0x14)),
        "mbr_params_page": hex32(read_word(data, 0x18)),
        "pselreset0": hex32(read_word(data, 0x200)),
        "pselreset1": hex32(read_word(data, 0x204)),
        "approtect": hex32(read_word(data, 0x208)),
        "nfcpins": hex32(read_word(data, 0x20C)),
    }


def decode_bootloader_settings(flash, backup_address):
    settings_address = len(flash) - PAGE_SIZE
    words = struct.unpack_from("<9I", flash, settings_address)
    settings_page = flash[settings_address : settings_address + PAGE_SIZE]
    backup_page = flash[backup_address : backup_address + PAGE_SIZE]
    return {
        "settings_address": hex32(settings_address),
        "backup_address": hex32(backup_address),
        "copies_identical": settings_page == backup_page,
        "crc": hex32(words[0]),
        "settings_version": words[1],
        "app_version": words[2],
        "bootloader_version": words[3],
        "bank_layout": words[4],
        "current_bank": words[5],
        "bank_0": {
            "image_size": words[6],
            "image_crc": hex32(words[7]),
            "bank_code": words[8],
        },
    }


def analyze(flash, uicr=None):
    softdevice = decode_softdevice(flash)
    vector_offsets = [0]
    if softdevice is not None:
        vector_offsets.append(int(softdevice["application_start"], 16))

    uicr_report = None
    if uicr is not None:
        uicr_report = decode_uicr(uicr)
        vector_offsets.append(int(uicr_report["bootloader_start"], 16))

    report = {
        "flash": {
            "sha256": hashlib.sha256(flash).hexdigest(),
            "size": len(flash),
            "non_erased_runs": non_erased_runs(flash),
            "vectors": [decode_vector(flash, offset) for offset in dict.fromkeys(vector_offsets)],
            "softdevice": softdevice,
        }
    }
    if uicr_report is not None:
        report["uicr"] = uicr_report
        report["bootloader_settings"] = decode_bootloader_settings(
            flash, int(uicr_report["mbr_params_page"], 16)
        )
    return report


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("flash", type=Path, help="full nRF52 code-flash dump")
    parser.add_argument("--uicr", type=Path, help="optional UICR window dump")
    return parser.parse_args()


def main():
    args = parse_args()
    flash = args.flash.read_bytes()
    uicr = args.uicr.read_bytes() if args.uicr else None
    print(json.dumps(analyze(flash, uicr), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
