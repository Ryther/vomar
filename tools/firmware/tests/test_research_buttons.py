from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[3]
class ResearchButtonsTests(unittest.TestCase):
 def test_click_dim_recovery_and_release_arbitration(self):
  with tempfile.TemporaryDirectory() as directory:
   exe=str(Path(directory)/'buttons-test')
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'firmware/research/src'),str(ROOT/'firmware/research/src/research_buttons.c'),str(Path(__file__).with_name('research_buttons_test.c')),'-o',exe],check=True)
   subprocess.run([exe],check=True)
