import csv
import json
from pathlib import Path
import re
import subprocess
import unittest
import shutil


REPO = Path(__file__).resolve().parents[3]
CONFIG = REPO / "tools" / "ghidra" / "nrf52840_peripherals.json"
EXPORTER = REPO / "tools" / "ghidra" / "ghidra_scripts" / "ExportPeripheralReferences.java"
RUNNER = REPO / "tools" / "ghidra" / "run-analysis.sh"
ADDRESS = re.compile(r"^0x[0-9a-f]{8}$")

OPTIONAL_ANALYSIS_AVAILABLE = all(path.is_file() for path in (REPO / "inputs/firmware/mesh/P561_Dimmer_Mesh.bin", REPO / "inputs/firmware/zigbee/P561_Dimmer_Zigbee.bin",)) and shutil.which("analyzeHeadless") is not None
OPTIONAL_REASON = "Optional original firmware inputs and Ghidra analyzeHeadless are required"


class PeripheralExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not CONFIG.is_file() or not EXPORTER.is_file():
            raise AssertionError("missing peripheral configuration or exporter")
        cls.config = json.loads(CONFIG.read_text(encoding="utf-8"))
        if not OPTIONAL_ANALYSIS_AVAILABLE:
            return
        for target in ("mesh", "zigbee"):
            output = REPO / "analysis" / target / "generated" / "peripheral_refs.tsv"
            if output.is_file():
                continue
            result = subprocess.run(
                [str(RUNNER), target, "--clean"], cwd=REPO, text=True,
                capture_output=True, check=False,
            )
            if result.returncode != 0:
                raise AssertionError(
                    f"{target} analysis failed:\n{result.stdout}\n{result.stderr}"
                )

    def test_ranges_are_non_overlapping_and_cover_priority_families(self):
        ranges = self.config["ranges"]
        self.assertEqual(self.config["schema_version"], 1)
        ordered = sorted(ranges, key=lambda item: int(item["start"], 0))
        self.assertEqual(ranges, ordered)
        previous_end = 0
        for item in ranges:
            start = int(item["start"], 0)
            end = int(item["end"], 0)
            self.assertLess(start, end)
            self.assertGreaterEqual(start, previous_end)
            previous_end = end
        names = " ".join(item["name"] for item in ranges)
        for family in (
            "GPIO", "GPIOTE", "TIMER", "RTC", "UART", "UARTE", "SPI", "SPIM",
            "TWI", "TWIM", "PWM", "PPI", "CLOCK", "NVMC", "UICR", "FICR",
        ):
            self.assertIn(family, names)
        by_name = {item["name"]: int(item["start"], 0) for item in ranges}
        self.assertEqual(by_name["SPI1_SPIM1_TWI1_TWIM1"], 0x40003000)
        self.assertEqual(by_name["WDT"], 0x40010000)

    @unittest.skipUnless(OPTIONAL_ANALYSIS_AVAILABLE, OPTIONAL_REASON)
    def test_peripheral_exports_follow_contract(self):
        ranges = {item["name"]: item for item in self.config["ranges"]}
        for target in ("mesh", "zigbee"):
            path = REPO / "analysis" / target / "generated" / "peripheral_refs.tsv"
            with path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(
                    handle, delimiter="\t", quoting=csv.QUOTE_NONE
                )
                self.assertEqual(
                    reader.fieldnames,
                    ["function_address", "instruction_address", "peripheral", "offset", "access", "evidence"],
                )
                rows = list(reader)
            self.assertGreater(len(rows), 0)
            keys = []
            for row in rows:
                if row["function_address"]:
                    self.assertRegex(row["function_address"], ADDRESS)
                self.assertRegex(row["instruction_address"], ADDRESS)
                self.assertIn(row["peripheral"], ranges)
                offset = int(row["offset"], 16)
                item = ranges[row["peripheral"]]
                self.assertLess(offset, int(item["end"], 0) - int(item["start"], 0))
                self.assertIn(row["access"], ("read", "write", "execute", "unknown"))
                self.assertIn(row["evidence"], ("memory_reference", "scalar_constant"))
                if row["evidence"] == "scalar_constant":
                    self.assertEqual(row["access"], "unknown")
                keys.append((int(row["instruction_address"], 16), row["peripheral"], offset, row["evidence"]))
            self.assertEqual(keys, sorted(keys))


if __name__ == "__main__":
    unittest.main()
