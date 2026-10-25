from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
PYTHON = Path(sys.executable)


class InitialInstallArtifactTests(unittest.TestCase):
    def test_storage_reset_preserves_images_and_excludes_uicr(self):
        script = '''
import sys
from pathlib import Path
from intelhex import IntelHex
sys.path.insert(0, str(Path(sys.argv[1]) / 'tools/firmware'))
from build_research import initial_install_image
directory=Path(sys.argv[2]); source=directory/'provision.hex'
image=IntelHex(); image[0]=0x12; image[0xc000]=0x34; image[0xb0000]=0x56
image.write_hex_file(str(source)); original=source.read_bytes()
result=IntelHex(str(initial_install_image(source)))
assert source.read_bytes()==original
assert result[0]==0x12 and result[0xc000]==0x34 and result[0xb0000]==0x56
assert len(result.addresses())==65539
assert max(result.addresses())==0xfffff
assert all(result[a]==255 for a in range(0xf0000,0x100000))
image[0x10001208]=0x5a;image.write_hex_file(str(source))
try:initial_install_image(source)
except ValueError:pass
else:raise AssertionError('UICR component was accepted')
'''
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([str(PYTHON), '-c', script, str(ROOT), directory], check=True)
