import importlib.util,json,struct,tempfile,unittest,hashlib,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('package',ROOT/'tools/firmware/restore_package.py');p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
class RestorePackageTests(unittest.TestCase):
 def fixture(self,folder,uid):
  ficr=bytearray(b'\xff'*4096);struct.pack_into('<II',ficr,0x60,*uid);struct.pack_into('<II',ficr,0xa4,0x01020304,0x00000506);struct.pack_into('<I',ficr,0x104,0x41414430)
  for name,data in [('flash',b'\x5a'*0xb0000+b'\xff'*0x3f000+b'\x5a'*0x11000),('uicr',b'\xff'*4096),('ficr',ficr)]: (folder/f'stock-{name}-a.bin').write_bytes(data)
 def test_package_uses_only_new_device_identity_and_backup(self):
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp);uid=(0x11223344,0x55667788);self.fixture(folder,uid);out,m=p.render_sources(folder,uid)
   self.assertEqual(m['restore_ble_address'],'C5:44:55:66:77:88');self.assertEqual(m['normal_ble_address'],'C5:06:01:02:03:04')
   self.assertEqual(m['flash_sha256'],hashlib.sha256((folder/'stock-flash-a.bin').read_bytes()).hexdigest())
   self.assertIn('0x11223344',(out/'bootstrap/main.c').read_text());self.assertNotIn('@VIMAR_',(out/'bootstrap/main.c').read_text())
   client=(out/'restore_via_ble.py').read_text();self.assertIn('UID=(0x11223344,0x55667788)',client);self.assertIn(m['flash_sha256'],client)
   header=(out/'probe_manifest.h').read_text();self.assertIn('PROBE_UID0 0x11223344U',header)
   expected=hashlib.sha256(b'\x5a'*4096).digest();pagepart=header.split('expected_pages[256][32] = {',1)[1].split('};',1)[0]
   values=bytes(int(x,16) for x in re.findall(r'0x([0-9a-f]+)',pagepart));self.assertEqual(values[:0xb0*32],expected*0xb0);self.assertEqual(values[0xb0*32:0xef*32],hashlib.sha256(b'\xff'*4096).digest()*0x3f)
 def test_wrong_ficr_blocks_package(self):
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp);self.fixture(folder,(1,2))
   with self.assertRaises(ValueError):p.render_sources(folder,(1,3))

 def test_exact_chip_revision_is_bound_from_ficr_without_broadening_uid(self):
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp);self.fixture(folder,(0x12345678,0x9abcdef0))
   ficr=bytearray((folder/'stock-ficr-a.bin').read_bytes());struct.pack_into('<I',ficr,0x104,0x41414630)
   (folder/'stock-ficr-a.bin').write_bytes(ficr);out,m=p.render_sources(folder,(0x12345678,0x9abcdef0))
   for name in ['main.c','bootstrap/main.c']:
    source=(out/name).read_text()
    self.assertIn('0x41414630',source)
    self.assertNotIn('0x41414430',source)
   self.assertEqual(m['chip_variant'],0x41414630)
   self.assertIn('0x12345678',(out/'bootstrap/main.c').read_text())

 def test_chip_variant_substitution_does_not_change_a_matching_uid_word(self):
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp);uid=(0x41414430,0x12345678);self.fixture(folder,uid)
   ficr=bytearray((folder/'stock-ficr-a.bin').read_bytes());struct.pack_into('<I',ficr,0x104,0x41414630)
   (folder/'stock-ficr-a.bin').write_bytes(ficr);out,_=p.render_sources(folder,uid)
   source=(out/'bootstrap/main.c').read_text()
   self.assertIn('NRF_FICR->DEVICEID[0]!=0x41414430',source)
   self.assertIn('NRF_FICR->INFO.VARIANT!=0x41414630',source)

 def test_non_erased_scratch_is_rejected_before_build(self):
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp);self.fixture(folder,(1,2));data=bytearray((folder/'stock-flash-a.bin').read_bytes());data[0xb1234]=0
   (folder/'stock-flash-a.bin').write_bytes(data)
   with self.assertRaises(ValueError):p.render_sources(folder,(1,2))


def test_cached_restore_cannot_be_reused_with_another_public_key(tmp_path,monkeypatch):
 import pytest
 uid=(1,2);out=tmp_path/'restore';out.mkdir()
 (tmp_path/'stock-flash-a.bin').write_bytes(b'stock')
 (out/'signing-public.pem').write_bytes(b'old public key')
 key=tmp_path/'new-public.pem';key.write_bytes(b'new public key')
 monkeypatch.setenv('VIMAR_SIGNING_PUBLIC_KEY',str(key))
 (out/'artifact-manifest.json').write_text(json.dumps({'deviceid':['00000001','00000002'],'flash_sha256':p.sha(b'stock'),'artifacts':{}}))
 with pytest.raises(ValueError,match='signing key'):p.build_package(tmp_path,uid)

def test_cached_restore_with_wrong_chip_revision_is_rejected(tmp_path,monkeypatch):
 import pytest
 uid=(1,2);out=tmp_path/'restore';out.mkdir()
 RestorePackageTests().fixture(tmp_path,uid)
 f=bytearray((tmp_path/'stock-ficr-a.bin').read_bytes());struct.pack_into('<I',f,0x104,0x41414630)
 (tmp_path/'stock-ficr-a.bin').write_bytes(f)
 key=tmp_path/'public.pem';key.write_bytes(b'public key');(out/'signing-public.pem').write_bytes(key.read_bytes())
 monkeypatch.setenv('VIMAR_SIGNING_PUBLIC_KEY',str(key))
 (out/'artifact-manifest.json').write_text(json.dumps({'deviceid':['00000001','00000002'],'flash_sha256':p.sha((tmp_path/'stock-flash-a.bin').read_bytes()),'artifacts':{}}))
 with pytest.raises(ValueError,match='chip variant'):p.build_package(tmp_path,uid)


def test_unresolved_template_token_refuses_rendering(tmp_path, monkeypatch):
 import pytest, shutil
 templates=tmp_path/'templates';shutil.copytree(p.TEMPLATES,templates)
 bootstrap=templates/'bootstrap/main.c'
 bootstrap.write_text(bootstrap.read_text()+'\n/* @VIMAR_UNKNOWN_BINDING@ */\n')
 provenance=json.loads((templates/'provenance.json').read_text())
 for row in provenance:
  if row['template']=='bootstrap/main.c':row['sha256']=hashlib.sha256(bootstrap.read_bytes()).hexdigest()
 (templates/'provenance.json').write_text(json.dumps(provenance))
 monkeypatch.setattr(p,'TEMPLATES',templates)
 monkeypatch.setattr(p,'ROOT',tmp_path)
 RestorePackageTests().fixture(tmp_path,(0x11223344,0x55667788))
 with pytest.raises(ValueError,match='template.*binding|binding.*template'):
  p.render_sources(tmp_path,(0x11223344,0x55667788))


def test_rendered_console_and_restorer_use_the_selected_devices_addresses(tmp_path,monkeypatch):
 uid=(0x11223344,0x55667788);RestorePackageTests().fixture(tmp_path,uid)
 output,manifest=p.render_sources(tmp_path,uid)
 # An old hardcoded DK console address or unresolved public placeholder breaks
 # this package-level contract, while physical writes are never executed.
 import sys
 spec=importlib.util.spec_from_file_location('generated_console',output/'research_console.py')
 console=importlib.util.module_from_spec(spec);spec.loader.exec_module(console)
 observed=[]
 async def offline(args):observed.append(args.address)
 monkeypatch.setattr(console,'run',offline)
 monkeypatch.setattr(sys,'argv',['generated_console','status'])
 console.main()
 assert observed==[manifest['normal_ble_address']]
 client=(output/'restore_via_ble.py').read_text()
 assert "ADDRESS='"+manifest['restore_ble_address']+"'" in client
 for relative in ['bootstrap/main.c','main.c','restore_via_ble.py','research_console.py']:
  assert '@VIMAR_' not in (output/relative).read_text()
