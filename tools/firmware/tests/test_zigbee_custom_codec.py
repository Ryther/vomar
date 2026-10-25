import subprocess,tempfile,unittest
from pathlib import Path
R=Path(__file__).resolve().parents[3]
class T(unittest.TestCase):
 def test_codec(self):
  with tempfile.TemporaryDirectory() as d:
   x=Path(d)/"t";src=[R/"tools/firmware/tests/zigbee_custom_codec_test.c",R/"firmware/src/zigbee_custom_codec.c",R/"firmware/src/dimmer_config.c"]
   p=subprocess.run(["cc","-std=c11","-Wall","-Wextra","-Werror","-I",str(R/"firmware/src"),*map(str,src),"-o",str(x)],text=True,capture_output=True);self.assertEqual(p.returncode,0,p.stderr);subprocess.run([str(x)],check=True)
if __name__=="__main__":unittest.main()
