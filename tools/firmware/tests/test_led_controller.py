import subprocess, tempfile, unittest
from pathlib import Path
REPO = Path(__file__).resolve().parents[3]
class LedControllerTests(unittest.TestCase):
    def test_led_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            exe = Path(temporary) / "led_test"
            cmd = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(REPO/"firmware/src"),
                   str(REPO/"tools/firmware/tests/led_controller_test.c"), str(REPO/"firmware/src/dimmer_config.c"),
                   str(REPO/"firmware/src/led_controller.c"), "-o", str(exe)]
            result = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            subprocess.run([str(exe)], check=True)
if __name__ == "__main__": unittest.main()
