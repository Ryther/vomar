#!/usr/bin/env python3
"""Validate generated DK single-slot/BLE-recovery images; never access hardware."""

import argparse
import hashlib
import re
import struct
import subprocess
import sys
from pathlib import Path


PARTITIONS = {
    "boot_partition": (0x00000, 0x0C000),
    "slot0_partition": (0x0C000, 0xA4000),
    "slot1_partition": (0xB0000, 0x40000),
    "storage_partition": (0xF0000, 0x07000),
    "zboss_nvram": (0xF7000, 0x08000),
    "zboss_product_config": (0xFF000, 0x01000),
}
REQUIRED = {
    "mcuboot": (
        "CONFIG_BOOT_FIRMWARE_LOADER", "CONFIG_BOOT_FIRMWARE_LOADER_ENTRANCE_GPIO",
        "CONFIG_BOOT_FIRMWARE_LOADER_NO_APPLICATION", "CONFIG_BOOT_VALIDATE_SLOT0",
        "CONFIG_BOOT_SIGNATURE_TYPE_ECDSA_P256", "CONFIG_DISABLE_FLASH_PATCH",
    ),
    "firmware": (
        "CONFIG_MCUBOOT_BOOTLOADER_MODE_FIRMWARE_UPDATER", "CONFIG_ZIGBEE_ADD_ON",
        "CONFIG_DISABLE_FLASH_PATCH",
    ),
    "vimar_recovery": (
        "CONFIG_MCUBOOT_BOOTLOADER_MODE_FIRMWARE_UPDATER",
        "CONFIG_MCUBOOT_APPLICATION_FIRMWARE_UPDATER", "CONFIG_MCUMGR_GRP_IMG",
        "CONFIG_MCUMGR_TRANSPORT_BT", "CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN",
        "CONFIG_BT_SMP", "CONFIG_BT_SETTINGS", "CONFIG_DISABLE_FLASH_PATCH",
    ),
}
FORBIDDEN = {
    "mcuboot": ("CONFIG_BOOT_SIGNATURE_TYPE_NONE", "CONFIG_BOOT_VALIDATE_SLOT0_ONCE"),
    "firmware": ("CONFIG_BT", "CONFIG_MCUMGR", "CONFIG_MCUBOOT_APPLICATION_FIRMWARE_UPDATER"),
    "vimar_recovery": ("CONFIG_MCUMGR_GRP_IMG_DIRECT_UPLOAD", "CONFIG_MCUMGR_GRP_ZBASIC"),
}


def read_config(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines()
                if line.startswith("CONFIG_") and "=" in line)


def validate_uicr_preservation(configs, compiler_defines):
    """Reject known automatic nRF52840 startup UICR writers.

    Check effective configurations and compiler macros: HEX address bounds
    alone cannot detect firmware writing UICR at runtime. This is a targeted
    startup check, not a general proof about arbitrary application code.
    """
    for image, config in configs.items():
        if config.get("CONFIG_DISABLE_FLASH_PATCH") == "y":
            raise ValueError(f"{image}: CONFIG_DISABLE_FLASH_PATCH writes DEBUGCTRL UICR")
        for macro in ("NRF_CONFIG_GPIO_AS_PINRESET", "CONFIG_GPIO_AS_PINRESET",
                      "NRF_CONFIG_NFCT_PINS_AS_GPIOS", "CONFIG_NFCT_PINS_AS_GPIOS"):
            if macro in compiler_defines.get(image, set()) or config.get(macro) == "y":
                raise ValueError(f"{image}: {macro} enables a startup UICR writer")


def read_partitions(dts):
    result = {}
    for name in PARTITIONS:
        match = re.search(r"\b" + name + r":\s*partition@[\da-fA-F]+\s*\{"
                          r"[^}]*?\breg\s*=\s*<\s*(0x[\da-fA-F]+)\s+"
                          r"(0x[\da-fA-F]+)\s*>", dts, re.S)
        if not match:
            raise ValueError(f"partition map: missing {name}")
        result[name] = tuple(int(value, 16) for value in match.groups())
    return result


def validate_contract(configs, layouts):
    for image, required in REQUIRED.items():
        if configs[image].get("CONFIG_SEGGER_RTT_INIT_MODE_ALWAYS") != "y":
            raise ValueError(f"{image}: requires CONFIG_SEGGER_RTT_INIT_MODE_ALWAYS=y")
        for setting in FORBIDDEN[image]:
            if configs[image].get(setting) == "y":
                raise ValueError(f"{image}: forbidden {setting}")
        for setting in required:
            if configs[image].get(setting) != "y":
                raise ValueError(f"{image}: requires {setting}=y")
        if layouts[image] != PARTITIONS:
            raise ValueError(f"{image}: partition map differs from recovery contract")
    if configs["vimar_recovery"].get("CONFIG_MCUMGR_GRP_IMG_UPDATABLE_IMAGE_NUMBER") != "1":
        raise ValueError("vimar_recovery: requires CONFIG_MCUMGR_GRP_IMG_UPDATABLE_IMAGE_NUMBER=1")


def validate_image(data, base, capacity):
    if len(data) < 32:
        raise ValueError("truncated image header")
    magic, _, header_size, _, payload_size, _ = struct.unpack_from("<IIHHII", data)
    if magic != 0x96F3B83D or header_size < 32 or payload_size < 8:
        raise ValueError("invalid MCUboot image header")
    if header_size + payload_size > len(data):
        raise ValueError("truncated image payload")
    if len(data) * 100 > (capacity - header_size) * 85:
        raise ValueError("image exceeds 15 percent flash reserve")
    stack, reset = struct.unpack_from("<II", data, header_size)
    if not (0x20000000 < stack <= 0x20040000) or stack % 8:
        raise ValueError("invalid initial stack pointer")
    if not reset & 1 or not base + header_size <= (reset & ~1) < base + header_size + payload_size:
        raise ValueError("image reset vector does not target its slot payload")


def read_hex(path):
    memory, upper = {}, 0
    for line in path.read_text().splitlines():
        record = bytes.fromhex(line.removeprefix(":"))
        if len(record) < 5 or sum(record) & 0xFF or record[0] != len(record) - 5:
            raise ValueError(f"invalid Intel HEX record in {path}")
        count, address, kind = record[0], int.from_bytes(record[1:3], "big"), record[3]
        payload = record[4:4 + count]
        if kind == 0:
            for offset, byte in enumerate(payload):
                absolute = upper + address + offset
                if absolute in memory and memory[absolute] != byte:
                    raise ValueError("conflicting Intel HEX data")
                memory[absolute] = byte
        elif kind in (2, 4):
            upper = int.from_bytes(payload, "big") << (4 if kind == 2 else 16)
        elif kind not in (1, 3, 5):
            raise ValueError(f"unsupported Intel HEX record type {kind}")
    return memory


def validate_merged_image(binary, signed_hex, merged, base, capacity):
    if not signed_hex or min(signed_hex) != base or max(signed_hex) >= base + capacity:
        raise ValueError("signed HEX extends outside its image slot")
    if any(merged.get(address) != byte for address, byte in signed_hex.items()):
        raise ValueError("signed image missing or changed in merged HEX")
    hex_binary = bytes(signed_hex.get(address, 0xFF)
                       for address in range(base, max(signed_hex) + 1))
    validate_image(binary, base, capacity)
    validate_image(hex_binary, base, capacity)
    header_size = struct.unpack_from("<H", binary, 8)[0]
    payload_size = struct.unpack_from("<I", binary, 12)[0]
    # NCS signs BIN and HEX separately. ECDSA signatures (and TLV lengths) may
    # differ; both signatures must be verified, while header/payload must match.
    end = header_size + payload_size
    if binary[:end] != hex_binary[:end]:
        raise ValueError("signed BIN and HEX have different header/payload")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--imgtool", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    args = parser.parse_args()
    build = args.build_dir
    configs = {name: read_config(build / name / "zephyr/.config") for name in REQUIRED}
    layouts = {}
    chosen = {"mcuboot": "boot_partition", "firmware": "slot0_partition",
              "vimar_recovery": "slot1_partition"}
    for name in REQUIRED:
        dts = (build / name / "zephyr/zephyr.dts").read_text()
        layouts[name] = read_partitions(dts)
        if not re.search(r"zephyr,code-partition\s*=\s*&" + chosen[name] + r"\s*;", dts):
            raise ValueError(f"{name}: wrong chosen code partition")
    validate_contract(configs, layouts)
    merged = read_hex(build / "merged_nrf52840dk_nrf52840.hex")
    for name, partition in chosen.items():
        directory = build / name / "zephyr"
        base, capacity = PARTITIONS[partition]
        if name != "mcuboot":
            path = directory / "zephyr.signed.bin"
            data = path.read_bytes()
            validate_image(data, base, capacity)
            hex_path = directory / "zephyr.signed.hex"
            validate_merged_image(data, read_hex(hex_path), merged, base, capacity)
            for signed in (path, hex_path):
                subprocess.run([sys.executable, str(args.imgtool), "verify", "-k",
                                str(args.key), str(signed)], check=True)
            print(f"{name}: signed={len(data)} bytes; sha256={hashlib.sha256(data).hexdigest()}")
        else:
            boot_hex = read_hex(directory / "zephyr.hex")
            if any(merged.get(address) != byte for address, byte in boot_hex.items()):
                raise ValueError("MCUboot missing or changed in merged HEX")
        output = subprocess.check_output(["arm-none-eabi-size", str(directory / "zephyr.elf")],
                                         text=True)
        text, data_size, bss = map(int, output.splitlines()[-1].split()[:3])
        if (text + data_size) * 100 > capacity * 85 or (data_size + bss) * 100 > 0x40000 * 85:
            raise ValueError(f"{name}: ELF exceeds 15 percent reserve")
        print(f"{name}: ELF flash={text + data_size}/{capacity}; static RAM={data_size + bss}/262144")
    print("PASS: partition maps, boot validation, authenticated primary-slot upload, signatures, "
          "link vectors, resource reserve and merged provisioning image")
    print("PENDING HARDWARE: boot trigger, BLE upload, interruption and crash recovery")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
