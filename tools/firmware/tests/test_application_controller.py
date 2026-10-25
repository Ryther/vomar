import subprocess,tempfile,unittest
from pathlib import Path
R=Path(__file__).resolve().parents[3]
class T(unittest.TestCase):
 def test_controller(self):
  with tempfile.TemporaryDirectory() as d:
   x=Path(d)/"t"; names=["application_controller_test.c"]
   src=[R/"tools/firmware/tests"/names[0],*[R/"firmware/src"/n for n in ["application_controller.c","dimmer_config.c","dimmer_model.c","gesture_classifier.c","local_action_mapper.c","led_controller.c"]]]
   p=subprocess.run(["cc","-std=c11","-Wall","-Wextra","-Werror","-I",str(R/"firmware/src"),*map(str,src),"-o",str(x)],text=True,capture_output=True)
   self.assertEqual(p.returncode,0,p.stderr);subprocess.run([str(x)],check=True)
if __name__=="__main__":unittest.main()
