import csv
from pathlib import Path
import re
import subprocess
import unittest
import shutil


REPO = Path(__file__).resolve().parents[3]
RUNNER = REPO / "tools" / "ghidra" / "run-analysis.sh"
EXPORTER = REPO / "tools" / "ghidra" / "ghidra_scripts" / "ExportStrings.java"
ADDRESS = re.compile(r"^0x[0-9a-f]{8}$")

OPTIONAL_ANALYSIS_AVAILABLE = all(path.is_file() for path in (REPO / "inputs/firmware/mesh/P561_Dimmer_Mesh.bin", REPO / "inputs/firmware/zigbee/P561_Dimmer_Zigbee.bin",)) and shutil.which("analyzeHeadless") is not None
OPTIONAL_REASON = "Optional original firmware inputs and Ghidra analyzeHeadless are required"


@unittest.skipUnless(OPTIONAL_ANALYSIS_AVAILABLE, OPTIONAL_REASON)
class StringExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not EXPORTER.is_file():
            raise AssertionError(f"missing exporter: {EXPORTER}")
        for target in ("mesh", "zigbee"):
            generated = REPO / "analysis" / target / "generated"
            if (generated / "strings.tsv").is_file() and (
                generated / "string_xrefs.tsv"
            ).is_file():
                continue
            result = subprocess.run(
                [str(RUNNER), target, "--clean"],
                cwd=REPO,
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode != 0:
                raise AssertionError(
                    f"{target} analysis failed:\n{result.stdout}\n{result.stderr}"
                )

    @staticmethod
    def rows(target, filename):
        path = REPO / "analysis" / target / "generated" / filename
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
            return reader.fieldnames, list(reader)

    def test_strings_are_stable_and_escaped(self):
        for target in ("mesh", "zigbee"):
            with self.subTest(target=target):
                header, rows = self.rows(target, "strings.tsv")
                self.assertEqual(header, ["address", "encoding", "length", "value"])
                self.assertGreater(len(rows), 10)
                addresses = [int(row["address"], 16) for row in rows]
                self.assertEqual(addresses, sorted(addresses))
                self.assertEqual(len(addresses), len(set(addresses)))
                for row in rows:
                    self.assertRegex(row["address"], ADDRESS)
                    self.assertGreater(int(row["length"]), 0)
                    self.assertNotIn("\t", row["value"])
                    self.assertNotIn("\r", row["value"])
                    self.assertNotIn("\n", row["value"])

    def test_xrefs_reference_exported_strings(self):
        for target in ("mesh", "zigbee"):
            with self.subTest(target=target):
                _, strings = self.rows(target, "strings.tsv")
                header, xrefs = self.rows(target, "string_xrefs.tsv")
                self.assertEqual(
                    header,
                    ["string_address", "from_address", "function_address", "ref_type"],
                )
                string_addresses = {row["address"] for row in strings}
                keys = []
                for row in xrefs:
                    self.assertIn(row["string_address"], string_addresses)
                    self.assertRegex(row["from_address"], ADDRESS)
                    if row["function_address"]:
                        self.assertRegex(row["function_address"], ADDRESS)
                    keys.append(
                        (
                            int(row["string_address"], 16),
                            int(row["from_address"], 16),
                            row["function_address"],
                            row["ref_type"],
                        )
                    )
                self.assertEqual(keys, sorted(keys))

    def test_known_mesh_source_anchor_is_present(self):
        _, strings = self.rows("mesh", "strings.tsv")
        anchors = [
            row for row in strings if "app_remote_dimmer_ble.c" in row["value"]
        ]
        self.assertEqual(len(anchors), 1)


if __name__ == "__main__":
    unittest.main()
