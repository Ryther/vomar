import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


class WirelessStatusLedTests(unittest.TestCase):
    def test_wireless_modes_preserve_faults_and_normal_profiles(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "wireless_status_led_test"
            command = [
                "cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                "-I", str(REPO / "firmware/src"),
                str(REPO / "tools/firmware/tests/wireless_status_led_test.c"),
                str(REPO / "firmware/src/wireless_status_led.c"),
                str(REPO / "firmware/src/led_controller.c"),
                str(REPO / "firmware/src/dimmer_config.c"),
                "-o", str(executable),
            ]
            built = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            executed = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(executed.returncode, 0, executed.stderr)


if __name__ == "__main__":
    unittest.main()
