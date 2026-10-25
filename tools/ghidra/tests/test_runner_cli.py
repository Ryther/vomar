import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import shutil


REPO = Path(__file__).resolve().parents[3]
RUNNER = REPO / "tools" / "ghidra" / "run-analysis.sh"


def run_runner(*args, cwd=None, env=None):
    if not RUNNER.is_file():
        raise AssertionError(f"missing runner: {RUNNER}")
    return subprocess.run(
        [str(RUNNER), *args],
        cwd=cwd or REPO,
        env=env or os.environ.copy(),
        text=True,
        capture_output=True,
        check=False,
    )


class RunnerCliTests(unittest.TestCase):
    def test_missing_target_is_usage_error(self):
        result = run_runner()
        self.assertEqual(result.returncode, 64)
        self.assertIn("usage:", result.stderr.lower())

    def test_unknown_target_is_usage_error(self):
        result = run_runner("unknown", "--dry-run")
        self.assertEqual(result.returncode, 64)
        self.assertIn("target", result.stderr.lower())

    @unittest.skipUnless((REPO / "inputs/firmware/mesh/P561_Dimmer_Mesh.bin").is_file() and shutil.which("analyzeHeadless"), "Optional original mesh firmware and Ghidra required")
    def test_dry_run_contains_exact_mesh_import_contract(self):
        result = run_runner("mesh", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(shutil.which("analyzeHeadless")), result.stdout)
        self.assertIn("-loader BinaryLoader", result.stdout)
        self.assertIn("-processor ARM:LE:32:Cortex", result.stdout)
        self.assertIn("-loader-baseAddr 0x00026000", result.stdout)
        self.assertIn("tools/ghidra/ghidra_scripts", result.stdout)
        self.assertIn("P561_Dimmer_Mesh.bin", result.stdout)

    @unittest.skipUnless((REPO / "inputs/firmware/zigbee/P561_Dimmer_Zigbee.bin").is_file() and shutil.which("analyzeHeadless"), "Optional original zigbee firmware and Ghidra required")
    def test_dry_run_contains_zigbee_source(self):
        result = run_runner("zigbee", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("P561_Dimmer_Zigbee.bin", result.stdout)

    @unittest.skipUnless((REPO / "inputs/firmware/mesh/P561_Dimmer_Mesh.bin").is_file() and shutil.which("analyzeHeadless"), "Optional original mesh firmware and Ghidra required")
    def test_runner_is_independent_of_current_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_runner("mesh", "--dry-run", cwd=directory)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(REPO / "inputs" / "firmware"), result.stdout)

    def test_dry_run_contains_no_hardware_mutation_tools(self):
        result = run_runner("mesh", "--dry-run")
        combined = (result.stdout + result.stderr).lower()
        for forbidden in ("nrfjprog", "--recover", "--eraseall", "--chiperase"):
            self.assertNotIn(forbidden, combined)

    @unittest.skipUnless((REPO / "inputs/firmware/mesh/P561_Dimmer_Mesh.bin").is_file() and shutil.which("analyzeHeadless"), "Optional original mesh firmware and Ghidra required")
    def test_analysis_creates_project_location_before_headless_invocation(self):
        with tempfile.TemporaryDirectory() as directory:
            fake_bin = Path(directory)
            invocation_log = fake_bin / "invocation.txt"
            analyzer = fake_bin / "analyzeHeadless"
            analyzer.write_text(
                "#!/bin/sh\n"
                "[ -d \"$1\" ] || exit 23\n"
                "printf '%s\\n' \"$1\" > \"$GHIDRA_TEST_LOG\"\n"
                "exit 0\n",
                encoding="utf-8",
            )
            analyzer.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}:{env['PATH']}"
            env["GHIDRA_TEST_LOG"] = str(invocation_log)
            result = run_runner("mesh", "--clean", env=env)
            project_location = Path(invocation_log.read_text(encoding="utf-8").strip())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing expected export", result.stderr)
        self.assertFalse(
            any(part.startswith(".") for part in project_location.parts),
            project_location,
        )


if __name__ == "__main__":
    unittest.main()
