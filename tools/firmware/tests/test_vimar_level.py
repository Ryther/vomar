from pathlib import Path
import subprocess,tempfile,unittest
R=Path(__file__).resolve().parents[3]
class VimarLevelTests(unittest.TestCase):
 def test_zigbee_mapping_endpoints_monotonicity_and_handoff_roundtrip(self):
  with tempfile.TemporaryDirectory() as d:
   exe=str(Path(d)/'level-test')
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(R/'firmware/src'),str(R/'firmware/src/vimar_level.c'),str(Path(__file__).with_name('vimar_level_test.c')),'-o',exe],check=True)
   subprocess.run([exe],check=True)
