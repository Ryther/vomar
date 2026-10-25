import json
from pathlib import Path
import subprocess
import unittest
import shutil


REPO = Path(__file__).resolve().parents[3]
RUNNER = REPO / "tools" / "ghidra" / "run-analysis.sh"
OUTPUT = REPO / "analysis" / "mesh" / "generated" / "program.json"

OPTIONAL_ANALYSIS_AVAILABLE = all(path.is_file() for path in (REPO / "inputs/firmware/mesh/P561_Dimmer_Mesh.bin",)) and shutil.which("analyzeHeadless") is not None
OPTIONAL_REASON = "Optional original firmware inputs and Ghidra analyzeHeadless are required"


@unittest.skipUnless(OPTIONAL_ANALYSIS_AVAILABLE, OPTIONAL_REASON)
class MetadataContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run(
            [str(RUNNER), "mesh", "--clean"],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(f"headless analysis failed:\n{result.stdout}\n{result.stderr}")

    def test_program_metadata_matches_mesh_evidence(self):
        self.assertTrue(OUTPUT.is_file(), f"missing metadata export: {OUTPUT}")
        metadata = json.loads(OUTPUT.read_text(encoding="utf-8"))
        self.assertEqual(metadata["schema_version"], 1)
        self.assertEqual(metadata["target"], "mesh")
        self.assertEqual(metadata["tool"], {"name": "Ghidra", "version": "12.1.2"})
        self.assertEqual(
            metadata["source"],
            {
                "path": "inputs/firmware/mesh/P561_Dimmer_Mesh.bin",
                "sha256": "8c0408c49fe3e35758a69e511faa154c2f1237512e1c1bfdf1061221db53f927",
            },
        )
        self.assertEqual(metadata["architecture"]["processor"], "ARM")
        self.assertEqual(metadata["architecture"]["endian"], "little")
        self.assertIn("Cortex", metadata["architecture"]["language"])
        self.assertTrue(
            any(block["start"] == "0x00026000" for block in metadata["memory_blocks"])
        )
        self.assertIn("0x00043f30", metadata["entry_points"])

    def test_metadata_has_no_volatile_or_absolute_values(self):
        metadata = json.loads(OUTPUT.read_text(encoding="utf-8"))
        forbidden_keys = ("time", "date", "uuid", "project_id")

        def visit(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    self.assertFalse(
                        any(token in key.lower() for token in forbidden_keys), key
                    )
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
            elif isinstance(value, str):
                self.assertNotIn(str(REPO), value)

        visit(metadata)


if __name__ == "__main__":
    unittest.main()
