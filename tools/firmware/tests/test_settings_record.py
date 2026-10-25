import subprocess, tempfile, unittest
from pathlib import Path
R=Path(__file__).resolve().parents[3]
class SettingsTests(unittest.TestCase):
 def test_settings(self):
  with tempfile.TemporaryDirectory() as d:
   exe=Path(d)/"t"; src=["tools/firmware/tests/settings_record_test.c","firmware/src/dimmer_config.c","firmware/src/settings_record.c","firmware/src/settings_store.c"]
   p=subprocess.run(["cc","-std=c11","-Wall","-Wextra","-Werror","-I",str(R/"firmware/src"),*(str(R/x) for x in src),"-o",str(exe)],text=True,capture_output=True)
   self.assertEqual(p.returncode,0,p.stderr); subprocess.run([str(exe)],check=True)
if __name__=="__main__": unittest.main()
