import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]


class DimmerConfigTests(unittest.TestCase):
    def test_config_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "dimmer_config_test"
            build = subprocess.run(
                [
                    "cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-I", str(REPO / "firmware/src"),
                    str(REPO / "tools/firmware/tests/dimmer_config_test.c"),
                    str(REPO / "firmware/src/dimmer_config.c"),
                    "-o", str(executable),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(build.returncode, 0, build.stderr)
            subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
