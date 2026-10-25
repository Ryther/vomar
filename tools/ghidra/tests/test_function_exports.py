import csv
from pathlib import Path
import re
import subprocess
import unittest
import shutil


REPO = Path(__file__).resolve().parents[3]
RUNNER = REPO / "tools" / "ghidra" / "run-analysis.sh"
ADDRESS = re.compile(r"^0x[0-9a-f]{8}$")

OPTIONAL_ANALYSIS_AVAILABLE = all(path.is_file() for path in (REPO / "inputs/firmware/mesh/P561_Dimmer_Mesh.bin", REPO / "inputs/firmware/zigbee/P561_Dimmer_Zigbee.bin",)) and shutil.which("analyzeHeadless") is not None
OPTIONAL_REASON = "Optional original firmware inputs and Ghidra analyzeHeadless are required"


@unittest.skipUnless(OPTIONAL_ANALYSIS_AVAILABLE, OPTIONAL_REASON)
class FunctionExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for target in ("mesh", "zigbee"):
            generated = REPO / "analysis" / target / "generated"
            if (generated / "functions.tsv").is_file() and (
                generated / "call_edges.tsv"
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
        if not path.is_file():
            raise AssertionError(f"missing export: {path}")
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
            return reader.fieldnames, list(reader)

    def test_function_inventory_contract_for_both_targets(self):
        handlers = {"mesh": "0x00043f30", "zigbee": "0x0002675c"}
        for target, handler in handlers.items():
            with self.subTest(target=target):
                header, rows = self.rows(target, "functions.tsv")
                self.assertEqual(
                    header,
                    ["address", "name", "size", "thunk", "entry", "callers", "callees"],
                )
                self.assertGreater(len(rows), 100)
                addresses = [row["address"] for row in rows]
                self.assertEqual(addresses, sorted(addresses, key=lambda item: int(item, 16)))
                self.assertEqual(len(addresses), len(set(addresses)))
                self.assertIn(handler, addresses)
                for row in rows:
                    self.assertRegex(row["address"], ADDRESS)
                    self.assertGreater(int(row["size"]), 0)
                    self.assertIn(row["thunk"], ("true", "false"))
                    self.assertIn(row["entry"], ("true", "false"))
                    int(row["callers"])
                    int(row["callees"])

    def test_call_edges_are_sorted_and_reference_known_functions(self):
        for target in ("mesh", "zigbee"):
            with self.subTest(target=target):
                _, functions = self.rows(target, "functions.tsv")
                header, edges = self.rows(target, "call_edges.tsv")
                self.assertEqual(header, ["caller", "callee", "callsite"])
                addresses = {row["address"] for row in functions}
                keys = [
                    tuple(int(row[field], 16) for field in ("caller", "callee", "callsite"))
                    for row in edges
                ]
                self.assertEqual(keys, sorted(keys))
                for row in edges:
                    self.assertIn(row["caller"], addresses)
                    self.assertIn(row["callee"], addresses)
                    self.assertRegex(row["callsite"], ADDRESS)


if __name__ == "__main__":
    unittest.main()
