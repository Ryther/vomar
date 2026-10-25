import importlib.util,tempfile,unittest,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('archives',ROOT/'tools/firmware/archive_tools.py');a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
class ArchiveTests(unittest.TestCase):
 def test_truncated_or_missing_archive_is_recreated_and_exact(self):
  with tempfile.TemporaryDirectory() as tmp:
   d=Path(tmp);source=d/'original.bin';source.write_bytes(b'original-device');archive=d/'backup.zip'
   for corrupt in [None,b'broken zip']:
    if corrupt is not None:archive.write_bytes(corrupt)
    a.ensure_archive(archive,{'flash.bin':source})
    with zipfile.ZipFile(archive) as z:self.assertEqual(z.read('flash.bin'),b'original-device');self.assertIsNone(z.testzip())
 def test_extra_or_stale_archive_entries_are_not_accepted(self):
  with tempfile.TemporaryDirectory() as tmp:
   d=Path(tmp);source=d/'original.bin';source.write_bytes(b'correct');archive=d/'backup.zip'
   with zipfile.ZipFile(archive,'w') as z:z.writestr('flash.bin',b'wrong');z.writestr('unexpected.bin',b'extra')
   a.ensure_archive(archive,{'flash.bin':source})
   with zipfile.ZipFile(archive) as z:self.assertEqual(z.namelist(),['flash.bin']);self.assertEqual(z.read('flash.bin'),b'correct')
