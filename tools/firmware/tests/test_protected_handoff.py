from pathlib import Path
import subprocess,tempfile,unittest
R=Path(__file__).resolve().parents[3]
class ProtectedHandoffTests(unittest.TestCase):
 def test_marker_crc_legacy_rejection_and_one_shot(self):
  with tempfile.TemporaryDirectory() as d:
   exe=str(Path(d)/'handoff')
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(R/'firmware/research/src'),str(R/'firmware/research/src/research_handoff.c'),str(Path(__file__).with_name('protected_handoff_test.c')),'-o',exe],check=True)
   subprocess.run([exe],check=True)
