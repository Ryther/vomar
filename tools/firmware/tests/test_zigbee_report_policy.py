import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]


class ZigbeeReportPolicyTests(unittest.TestCase):
    def test_policy_behavior(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "zigbee_report_policy_test"
            build = subprocess.run(
                [
                    "cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-I", str(REPO / "firmware/src"),
                    str(REPO / "tools/firmware/tests/zigbee_report_policy_test.c"),
                    str(REPO / "firmware/src/zigbee_report_policy.c"),
                    "-o", str(executable),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(build.returncode, 0, build.stderr)
            subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
