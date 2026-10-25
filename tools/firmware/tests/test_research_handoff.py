from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[3]
class ResearchHandoffTests(unittest.TestCase):
 def test_recovery_handoff_is_persisted_atomic_one_shot_and_fail_closed(self):
  with tempfile.TemporaryDirectory() as directory:
   exe=str(Path(directory)/'handoff-test')
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'firmware/research/src'),str(ROOT/'firmware/research/src/research_handoff.c'),str(Path(__file__).with_name('research_handoff_test.c')),'-o',exe],check=True)
   subprocess.run([exe],check=True)
