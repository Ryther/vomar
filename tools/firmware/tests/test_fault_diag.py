from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


class FaultDiagTests(unittest.TestCase):
    def test_record_integrity_capture_and_interrupted_publication(self):
        here = Path(__file__).parent
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory) / "fault_diag")
            subprocess.run([
                "cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=undefined", "-fno-sanitize-recover=all",
                "-I", str(ROOT / "firmware/src"),
                "-include", str(here / "fault_diag_test_hooks.h"),
                str(ROOT / "firmware/src/fault_diag.c"),
                str(here / "fault_diag_test.c"), "-o", executable,
            ], check=True)
            result = subprocess.run([executable], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("fault diagnostics behavioral tests passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
