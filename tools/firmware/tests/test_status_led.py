from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[3]
class StatusLedTests(unittest.TestCase):
    def test_alive_indicator_and_authenticated_pulse_keep_both_polarities_lit(self):
        with tempfile.TemporaryDirectory() as directory:
            exe = str(Path(directory) / 'status-led-test')
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-I', str(ROOT / 'firmware/research/src'),
                            str(ROOT / 'firmware/research/src/research_status_led.c'),
                            str(Path(__file__).with_name('status_led_test.c')),
                            '-o', exe], check=True)
            subprocess.run([exe], check=True)
