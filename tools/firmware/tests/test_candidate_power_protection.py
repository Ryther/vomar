from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[3]

class CandidateProtectionTests(unittest.TestCase):
    def test_qualification_faults_gaps_and_record_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            exe = str(Path(directory) / 'protection')
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-I', str(ROOT / 'firmware/src'),
                            str(ROOT / 'firmware/src/candidate_power_protection.c'),
                            str(Path(__file__).with_name('candidate_power_protection_test.c')),
                            '-o', exe], check=True)
            subprocess.run([exe], check=True)
