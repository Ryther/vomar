"""Real two-extent mapping refuses recovery/code collisions and unsafe IO."""
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[3]
def test_two_extent_geometry_and_bounded_reader(tmp_path):
 out=tmp_path/'split'
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=undefined','-I',str(ROOT/'firmware/ota'),str(ROOT/'tools/firmware/tests/ota_split_stage_test.c'),str(ROOT/'firmware/ota/ota_split_stage.c'),'-o',str(out)],check=True)
 subprocess.run([str(out)],check=True)
