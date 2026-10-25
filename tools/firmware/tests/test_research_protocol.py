from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


class ResearchProtocolTests(unittest.TestCase):
    def test_protocol_validation_state_and_pwm_range(self):
        with tempfile.TemporaryDirectory() as directory:
            exe = str(Path(directory) / 'research-test')
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-I', str(ROOT / 'firmware/research/src'),
                            str(ROOT / 'firmware/research/src/research_protocol.c'),
                            str(Path(__file__).with_name('research_protocol_test.c')),
                            '-o', exe], check=True)
            subprocess.run([exe], check=True)
