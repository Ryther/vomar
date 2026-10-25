from pathlib import Path
import subprocess,tempfile,unittest
R=Path(__file__).resolve().parents[3]
class BootTraceTests(unittest.TestCase):
 def test_intent_matching_bounded_history_and_integrity(self):
  with tempfile.TemporaryDirectory() as d:
   exe=str(Path(d)/'trace')
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(R/'firmware/src'),str(R/'firmware/src/boot_trace.c'),str(Path(__file__).with_name('boot_trace_test.c')),'-o',exe],check=True)
   subprocess.run([exe],check=True)
