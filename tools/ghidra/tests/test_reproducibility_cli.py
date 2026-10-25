import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[3]
VERIFIER = REPO / "tools" / "ghidra" / "verify-reproducibility.sh"


def tree_hash(root):
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class ReproducibilityCliTests(unittest.TestCase):
    def run_verifier(self, *args, env=None):
        if not VERIFIER.is_file():
            raise AssertionError(f"missing verifier: {VERIFIER}")
        return subprocess.run(
            [str(VERIFIER), *args], cwd=REPO, env=env or os.environ.copy(),
            text=True, capture_output=True, check=False,
        )

    def test_invalid_target_is_usage_error(self):
        result = self.run_verifier("invalid")
        self.assertEqual(result.returncode, 64)
        self.assertIn("usage:", result.stderr.lower())

    def test_two_identical_runs_pass_and_temporary_state_is_cleaned(self):
        with tempfile.TemporaryDirectory() as directory:
            env, output, repro = self.fake_environment(Path(directory), "stable")
            before_inputs = tree_hash(REPO / "inputs")
            before_third_party = tree_hash(REPO / "third_party")
            result = self.run_verifier("mesh", env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("mesh: reproducible", result.stdout)
            self.assertEqual(list(repro.iterdir()), [])
            self.assertEqual(before_inputs, tree_hash(REPO / "inputs"))
            self.assertEqual(before_third_party, tree_hash(REPO / "third_party"))
            self.assertTrue((output / "mesh" / "generated" / "sample.tsv").is_file())

    def test_mismatch_reports_first_differing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            env, _, repro = self.fake_environment(Path(directory), "different")
            result = self.run_verifier("zigbee", env=env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("sample.tsv", result.stderr)
            self.assertEqual(list(repro.iterdir()), [])

    @staticmethod
    def fake_environment(root, mode):
        output = root / "analysis"
        repro = root / "reproducibility"
        output.mkdir()
        repro.mkdir()
        counter = root / "counter"
        runner = root / "fake-runner"
        runner.write_text(
            "#!/bin/sh\n"
            "count=0\n"
            "[ ! -f \"$FAKE_COUNTER\" ] || count=$(cat \"$FAKE_COUNTER\")\n"
            "count=$((count + 1))\n"
            "printf '%s' \"$count\" > \"$FAKE_COUNTER\"\n"
            "mkdir -p \"$GHIDRA_OUTPUT_ROOT/$1/generated\"\n"
            "value=stable\n"
            "[ \"$FAKE_MODE\" != different ] || value=$count\n"
            "printf '%s\\n' \"$value\" > \"$GHIDRA_OUTPUT_ROOT/$1/generated/sample.tsv\"\n",
            encoding="utf-8",
        )
        runner.chmod(0o755)
        env = os.environ.copy()
        env.update({
            "GHIDRA_RUNNER": str(runner),
            "GHIDRA_OUTPUT_ROOT": str(output),
            "GHIDRA_REPRO_ROOT": str(repro),
            "FAKE_COUNTER": str(counter),
            "FAKE_MODE": mode,
        })
        return env, output, repro


if __name__ == "__main__":
    unittest.main()
