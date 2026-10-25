from pathlib import Path
import subprocess,tempfile,unittest
R=Path(__file__).resolve().parents[3]
class VimarButtonsTests(unittest.TestCase):
 def test_recovery_chord_suppresses_local_gestures_until_full_release(self):
  with tempfile.TemporaryDirectory() as d:
   exe=str(Path(d)/'buttons')
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(R/'firmware/src'),str(R/'firmware/src/vimar_buttons.c'),str(Path(__file__).with_name('vimar_buttons_test.c')),'-o',exe],check=True)
   subprocess.run([exe],check=True)
