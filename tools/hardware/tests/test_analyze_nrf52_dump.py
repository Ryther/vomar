import json
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "tools/hardware/analyze_nrf52_dump.py"


class AnalyzeNrf52DumpTests(unittest.TestCase):
    def test_cli_reports_flash_layout_without_unique_device_data(self):
        flash = bytearray(b"\xff" * 0x100000)
        struct.pack_into("<II", flash, 0x000000, 0x20000400, 0x00000A81)
        struct.pack_into("<IIII", flash, 0x003000, 0xFFFFFF2C, 0x51B1E5DB, 0x00026000, 0xFFFF00B6)
        struct.pack_into("<II", flash, 0x026000, 0x20008000, 0x0002675D)
        struct.pack_into("<II", flash, 0x0F8000, 0x20040000, 0x000F82B5)
        settings_words = (0xBF3D99A1, 2, 0x27D9, 1, 0, 0, 0x53FB4, 0x0F543892, 1)
        struct.pack_into("<9I", flash, 0x0FE000, *settings_words)
        struct.pack_into("<9I", flash, 0x0FF000, *settings_words)

        uicr = bytearray(b"\xff" * 0x1000)
        struct.pack_into("<II", uicr, 0x14, 0x000F8000, 0x000FE000)
        struct.pack_into("<IIII", uicr, 0x200, 0x12, 0x12, 0xFFFFFFFF, 0xFFFFFFFE)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            flash_path = root / "flash.bin"
            uicr_path = root / "uicr.bin"
            flash_path.write_bytes(flash)
            uicr_path.write_bytes(uicr)

            result = subprocess.run(
                ["python3", str(SCRIPT), str(flash_path), "--uicr", str(uicr_path)],
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["flash"]["size"], 0x100000)
        self.assertEqual(
            report["flash"]["non_erased_runs"],
            [
                {"start": "0x000000", "end_exclusive": "0x001000", "pages": 1},
                {"start": "0x003000", "end_exclusive": "0x004000", "pages": 1},
                {"start": "0x026000", "end_exclusive": "0x027000", "pages": 1},
                {"start": "0x0f8000", "end_exclusive": "0x0f9000", "pages": 1},
                {"start": "0x0fe000", "end_exclusive": "0x100000", "pages": 2},
            ],
        )
        self.assertEqual(
            report["flash"]["vectors"],
            [
                {"offset": "0x000000", "initial_sp": "0x20000400", "reset_vector": "0x00000a81", "plausible": True},
                {"offset": "0x026000", "initial_sp": "0x20008000", "reset_vector": "0x0002675d", "plausible": True},
                {"offset": "0x0f8000", "initial_sp": "0x20040000", "reset_vector": "0x000f82b5", "plausible": True},
            ],
        )
        self.assertEqual(
            report["flash"]["softdevice"],
            {"offset": "0x003000", "magic": "0x51b1e5db", "application_start": "0x00026000", "fwid": "0x00b6"},
        )
        self.assertEqual(
            report["uicr"],
            {
                "bootloader_start": "0x000f8000",
                "mbr_params_page": "0x000fe000",
                "pselreset0": "0x00000012",
                "pselreset1": "0x00000012",
                "approtect": "0xffffffff",
                "nfcpins": "0xfffffffe",
            },
        )
        self.assertEqual(
            report["bootloader_settings"],
            {
                "settings_address": "0x000ff000",
                "backup_address": "0x000fe000",
                "copies_identical": True,
                "crc": "0xbf3d99a1",
                "settings_version": 2,
                "app_version": 0x27D9,
                "bootloader_version": 1,
                "bank_layout": 0,
                "current_bank": 0,
                "bank_0": {
                    "image_size": 0x53FB4,
                    "image_crc": "0x0f543892",
                    "bank_code": 1,
                },
            },
        )
        self.assertNotIn("ficr", report)
        self.assertNotIn(str(flash_path), result.stdout)


if __name__ == "__main__":
    unittest.main()
