import csv
import json
from pathlib import Path
import re
import subprocess
import unittest
import shutil


REPO = Path(__file__).resolve().parents[3]
CONFIG = REPO / "tools" / "ghidra" / "decompile_targets.json"
EXPORTER = REPO / "tools" / "ghidra" / "ghidra_scripts" / "ExportSelectedDecompilation.java"
RUNNER = REPO / "tools" / "ghidra" / "run-analysis.sh"
SAFE_FILE = re.compile(r"^[a-z0-9_]+-0x[0-9a-f]{8}\.c$")

OPTIONAL_ANALYSIS_AVAILABLE = all(path.is_file() for path in (REPO / "inputs/firmware/mesh/P561_Dimmer_Mesh.bin", REPO / "inputs/firmware/zigbee/P561_Dimmer_Zigbee.bin",)) and shutil.which("analyzeHeadless") is not None
OPTIONAL_REASON = "Optional original firmware inputs and Ghidra analyzeHeadless are required"


class DecompilationExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not CONFIG.is_file() or not EXPORTER.is_file():
            raise AssertionError("missing decompilation configuration or exporter")
        cls.config = json.loads(CONFIG.read_text(encoding="utf-8"))
        if not OPTIONAL_ANALYSIS_AVAILABLE:
            return
        for target in ("mesh", "zigbee"):
            index = REPO / "analysis" / target / "generated" / "decompilation" / "index.tsv"
            if index.is_file():
                continue
            result = subprocess.run(
                [str(RUNNER), target, "--clean"], cwd=REPO, text=True,
                capture_output=True, check=False,
            )
            if result.returncode != 0:
                raise AssertionError(
                    f"{target} analysis failed:\n{result.stdout}\n{result.stderr}"
                )

    def test_configuration_uses_evidence_safe_labels(self):
        self.assertEqual(self.config["schema_version"], 1)
        entries = self.config["targets"]
        configured = {(entry["target"], entry["address"]) for entry in entries}
        self.assertIn(("mesh", "0x00043f30"), configured)
        self.assertIn(("zigbee", "0x0002675c"), configured)
        self.assertIn(("mesh", "0x00045e24"), configured)
        self.assertIn(("zigbee", "0x0002a7c4"), configured)
        seen = set()
        for entry in entries:
            self.assertIn(entry["classification"], ("CONFIRMED", "STRONG INFERENCE", "HYPOTHESIS"))
            self.assertTrue(entry["evidence"].strip())
            if entry["classification"] != "CONFIRMED":
                self.assertTrue(entry["label"].startswith(("candidate_", "probable_")))
            self.assertNotIn((entry["target"], entry["label"]), seen)
            seen.add((entry["target"], entry["label"]))

    @unittest.skipUnless(OPTIONAL_ANALYSIS_AVAILABLE, OPTIONAL_REASON)
    def test_index_and_decompilation_are_deterministic(self):
        expected = {"mesh": "0x00043f30", "zigbee": "0x0002675c"}
        for target, address in expected.items():
            directory = REPO / "analysis" / target / "generated" / "decompilation"
            with (directory / "index.tsv").open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
                self.assertEqual(reader.fieldnames, ["label", "address", "status", "file"])
                rows = list(reader)
            configured = [
                entry for entry in self.config["targets"] if entry["target"] == target
            ]
            self.assertEqual(len(rows), len(configured))
            self.assertIn(address, {row["address"] for row in rows})
            for row in rows:
                self.assertEqual(row["status"], "success")
                self.assertRegex(row["file"], SAFE_FILE)
                text = (directory / row["file"]).read_text(encoding="utf-8")
                self.assertTrue(text.strip())
                self.assertNotIn(str(REPO), text)
                self.assertNotRegex(text.lower(), r"timestamp|generated on")
                self.assertTrue(text.endswith("\n"))


if __name__ == "__main__":
    unittest.main()
