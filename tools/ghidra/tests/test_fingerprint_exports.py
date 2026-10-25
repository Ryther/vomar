import csv
from pathlib import Path
import re
import subprocess
import unittest
import shutil


REPO = Path(__file__).resolve().parents[3]
RUNNER = REPO / "tools" / "ghidra" / "run-analysis.sh"
EXPORTER = REPO / "tools" / "ghidra" / "ghidra_scripts" / "ExportFunctionFingerprints.java"
SHA256 = re.compile(r"^[0-9a-f]{64}$")

OPTIONAL_ANALYSIS_AVAILABLE = all(path.is_file() for path in (REPO / "inputs/firmware/mesh/P561_Dimmer_Mesh.bin", REPO / "inputs/firmware/zigbee/P561_Dimmer_Zigbee.bin",)) and shutil.which("analyzeHeadless") is not None
OPTIONAL_REASON = "Optional original firmware inputs and Ghidra analyzeHeadless are required"


@unittest.skipUnless(OPTIONAL_ANALYSIS_AVAILABLE, OPTIONAL_REASON)
class FingerprintExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not EXPORTER.is_file():
            raise AssertionError(f"missing fingerprint exporter: {EXPORTER}")
        for target in ("mesh", "zigbee"):
            output = REPO / "analysis" / target / "generated" / "function_fingerprints.tsv"
            if output.is_file():
                continue
            result = subprocess.run(
                [str(RUNNER), target, "--clean"], cwd=REPO, text=True,
                capture_output=True, check=False,
            )
            if result.returncode != 0:
                raise AssertionError(f"{target} analysis failed:\n{result.stdout}\n{result.stderr}")

    @staticmethod
    def read(target, filename):
        path = REPO / "analysis" / target / "generated" / filename
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE))

    def test_fingerprint_contract_and_function_coverage(self):
        handlers = {"mesh": "0x00043f30", "zigbee": "0x0002675c"}
        expected_header = [
            "address", "byte_size", "instruction_count", "basic_blocks",
            "cyclomatic", "calls", "unique_constants", "mnemonic_sha256",
            "exact_bytes_sha256",
        ]
        for target, handler in handlers.items():
            with self.subTest(target=target):
                rows = self.read(target, "function_fingerprints.tsv")
                functions = self.read(target, "functions.tsv")
                self.assertEqual(list(rows[0]), expected_header)
                addresses = [row["address"] for row in rows]
                self.assertEqual(addresses, [row["address"] for row in functions])
                self.assertIn(handler, addresses)
                for row in rows:
                    self.assertGreater(int(row["byte_size"]), 0)
                    self.assertGreater(int(row["instruction_count"]), 0)
                    self.assertGreater(int(row["basic_blocks"]), 0)
                    self.assertGreaterEqual(int(row["cyclomatic"]), 1)
                    self.assertGreaterEqual(int(row["calls"]), 0)
                    self.assertGreaterEqual(int(row["unique_constants"]), 0)
                    self.assertRegex(row["mnemonic_sha256"], SHA256)
                    self.assertRegex(row["exact_bytes_sha256"], SHA256)


if __name__ == "__main__":
    unittest.main()
