#!/usr/bin/env python3

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
GENERATOR = REPO_ROOT / "tools" / "hardware" / "generate_nrf52840_dev_uicr.py"


def parse_intel_hex(path: Path) -> dict[int, int]:
    memory: dict[int, int] = {}
    upper_address = 0
    saw_eof = False

    for raw_line in path.read_text(encoding="ascii").splitlines():
        record = bytes.fromhex(raw_line.removeprefix(":"))
        if sum(record) & 0xFF:
            raise AssertionError(f"invalid checksum: {raw_line}")

        length = record[0]
        address = int.from_bytes(record[1:3], "big")
        record_type = record[3]
        data = record[4 : 4 + length]
        self_checksum = record[4 + length]
        del self_checksum

        if record_type == 0x00:
            for offset, value in enumerate(data):
                memory[upper_address + address + offset] = value
        elif record_type == 0x01:
            saw_eof = True
        elif record_type == 0x04:
            upper_address = int.from_bytes(data, "big") << 16
        else:
            raise AssertionError(f"unexpected record type: {record_type:#x}")

    if not saw_eof:
        raise AssertionError("missing EOF record")
    return memory


class GenerateNrf52840DevUicrTest(unittest.TestCase):
    def test_generates_only_development_approtect_word(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "nrf52840-dev-uicr.hex"
            result = subprocess.run(
                [sys.executable, str(GENERATOR), str(output)],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                parse_intel_hex(output),
                {
                    0x10001208: 0x5A,
                    0x10001209: 0x00,
                    0x1000120A: 0x00,
                    0x1000120B: 0x00,
                },
            )


if __name__ == "__main__":
    unittest.main()
