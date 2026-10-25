import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]


class GestureClassifierTests(unittest.TestCase):
    def test_gesture_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "gesture_classifier_test"
            sources = [
                "tools/firmware/tests/gesture_classifier_test.c",
                "firmware/src/dimmer_config.c",
                "firmware/src/gesture_classifier.c",
                "firmware/src/local_action_mapper.c",
            ]
            build = subprocess.run(
                ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                 "-I", str(REPO / "firmware/src"),
                 *(str(REPO / source) for source in sources), "-o", str(executable)],
                text=True, capture_output=True,
            )
            self.assertEqual(build.returncode, 0, build.stderr)
            subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
