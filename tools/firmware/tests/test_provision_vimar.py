import importlib.util,json,tempfile,unittest,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('provision',ROOT/'tools/firmware/provision_vimar.py');p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
class ProvisionTests(unittest.TestCase):
 def test_identity_rejects_dk_and_requires_consistent_observations(self):
  from unittest.mock import patch
  with patch.object(p,'KNOWN_DKS',{(0x31415926,0x27182818)}):
   self.assertFalse(p.stable_target([(0x31415926,0x27182818)]*3))
   self.assertFalse(p.stable_target([(1,2)]*2))
   self.assertFalse(p.stable_target([(1,2),(1,3),(1,2)]))
   self.assertTrue(p.stable_target([(0x22334455,0x66778899)]*3))
 def test_ieee_is_device_specific(self):
  self.assertEqual(p.ieee((0x22334455,0x66778899)),'0xf4ce365566778899')
  self.assertEqual(p.ieee((0x11223344,0x55667788)),'0xf4ce364455667788')
 def test_backup_requires_two_complete_identical_reads(self):
  with tempfile.TemporaryDirectory() as tmp:
   d=Path(tmp)
   for kind,size in p.BACKUP_SIZES.items():
    for suffix in ['a','b']:(d/f'stock-{kind}-{suffix}.bin').write_bytes(b'\xff'*size)
   self.assertTrue(p.verify_backup(d)['flash']['double_read_identical'])
   (d/'stock-flash-b.bin').write_bytes(b'\x00'*p.BACKUP_SIZES['flash'])
   with self.assertRaises(ValueError):p.verify_backup(d)
 def test_plan_tamper_or_target_change_blocks_flash(self):
  with tempfile.TemporaryDirectory() as tmp:
   d=Path(tmp);(d/'initial-install.hex').write_text('image')
   plan={'uid':[1,2],'image_sha256':hashlib.sha256(b'image').hexdigest(),'backup_verified':True,'restore_verified':True}
   p.validate_flash_gate(d,plan,(1,2))
   with self.assertRaises(ValueError):p.validate_flash_gate(d,plan,(1,3))
   plan['restore_verified']=False
   with self.assertRaises(ValueError):p.validate_flash_gate(d,plan,(1,2))
   plan['restore_verified']=True;(d/'initial-install.hex').write_text('changed')
   with self.assertRaises(ValueError):p.validate_flash_gate(d,plan,(1,2))
 def test_page_prediction_preserves_unaddressed_pages(self):
  before=b'\x12'*8192
  result=p.expected_flash(before,{3:0x42})
  self.assertEqual(result[3],0x42);self.assertEqual(result[:3],b'\xff'*3)
  self.assertEqual(result[4096:],before[4096:])
  with self.assertRaises(ValueError):p.expected_flash(before,{0x10001000:0})


def test_frozen_ota_pair_maps_only_its_two_slots_and_preserves_evidence(tmp_path):
 from intelhex import IntelHex
 pair={'manifest_path':'source.json','manifest_sha256':'a'*64,'qualification':{'path':'qualification.json','sha256':hashlib.sha256(b'{}').hexdigest()},'qualification_data':b'{}','main':{'data':b'main image','sha256':hashlib.sha256(b'main image').hexdigest(),'version':'0.5.3+0'},'recovery':{'data':b'recovery image','sha256':hashlib.sha256(b'recovery image').hexdigest(),'version':'0.7.1+0'}}
 main,recovery=p.freeze_ota_pair(tmp_path,pair)
 for file,base,data in [(main,0xc000,b'main image'),(recovery,0xb0000,b'recovery image')]:
  image=IntelHex(str(file));assert image.addresses()==list(range(base,base+len(data)));assert bytes(image.tobinarray())==data
 assert (tmp_path/'ota-qualification.json').read_bytes()==b'{}'
 assert json.loads((tmp_path/'ota-pair-provenance.json').read_text())['qualification']['sha256']==pair['qualification']['sha256']
 assert p.freeze_ota_pair(tmp_path,pair)==(main,recovery)
 (tmp_path/'qualified-main.signed.bin').write_bytes(b'changed')
 with __import__('pytest').raises(ValueError,match='Existing'):p.freeze_ota_pair(tmp_path,pair)

def test_unqualified_pair_is_rejected_before_any_hardware_probe(tmp_path,monkeypatch):
 import pytest
 evidence=tmp_path/'evidence.json';evidence.write_text('{"schema_version":1,"zigbee_ota_completed":false}')
 manifest=tmp_path/'pair.json';manifest.write_text(json.dumps({'schema_version':1,'qualification':{'path':str(evidence),'sha256':hashlib.sha256(evidence.read_bytes()).hexdigest()}}))
 def no_probe(*args):pytest.fail('Unqualified OTA pair must not probe hardware')
 monkeypatch.setattr(p,'detect',no_probe);monkeypatch.setattr(__import__('sys'),'argv',['provision_vimar.py','--serial','123','--ota-release',str(manifest),'--prepare-only'])
 with pytest.raises(ValueError,match='qualification'):p.main()

def test_frozen_pair_rejects_out_of_slot_data_before_writing(tmp_path):
 import pytest
 data=b'X'*(0x40000+1)
 pair={'manifest_path':'source','manifest_sha256':'0'*64,'qualification':{'sha256':hashlib.sha256(b'{}').hexdigest()},'qualification_data':b'{}','main':{'data':data,'sha256':hashlib.sha256(data).hexdigest(),'version':'0.5.3+0'},'recovery':{'data':data,'sha256':hashlib.sha256(data).hexdigest(),'version':'0.7.1+0'}}
 with pytest.raises(ValueError,match='component'):p.freeze_ota_pair(tmp_path,pair)
 assert not (tmp_path/'qualified-recovery.signed.bin').exists()


def test_resume_cannot_silently_ignore_another_ota_selection(tmp_path):
 import pytest
 (tmp_path/'plan.json').write_text(json.dumps({'ota_pair':{'manifest_sha256':'a'*64}}))
 with pytest.raises(ValueError,match='selection'):p.validate_resume_selection(tmp_path,None,{'manifest_sha256':'b'*64})
 p.validate_resume_selection(tmp_path,None,{'manifest_sha256':'a'*64})

def test_resume_cannot_silently_ignore_another_explicit_main(tmp_path):
 import pytest
 source=tmp_path/'another.hex';source.write_text('another image')
 (tmp_path/'plan.json').write_text(json.dumps({'components':[{'name':'main','sha256':'0'*64}]}))
 with pytest.raises(ValueError,match='selection'):p.validate_resume_selection(tmp_path,source,None)

def test_partial_ota_preparation_cannot_fall_back_to_legacy(tmp_path):
 import pytest
 (tmp_path/'ota-pair-provenance.json').write_text(json.dumps({'manifest_sha256':'a'*64}))
 with pytest.raises(ValueError,match='selection'):p.validate_resume_selection(tmp_path,None,None)
 with pytest.raises(ValueError,match='selection'):p.validate_resume_selection(tmp_path,None,{'manifest_sha256':'b'*64})
 p.validate_resume_selection(tmp_path,None,{'manifest_sha256':'a'*64})

def test_ota_flash_gate_imports_from_a_standalone_cli_path(tmp_path):
 import subprocess,sys
 image=tmp_path/'initial-install.hex';image.write_text('prepared hex')
 checks={'schema_version':1,'main_sha256':'1'*64,'recovery_sha256':'2'*64,**{k:True for k in ['zigbee_ota_completed','postboot_hash_verified','ble_recovery_verified','power_cut_recovery_verified']}}
 evidence=tmp_path/'evidence.json';evidence.write_text(json.dumps(checks))
 plan={'uid':[1,2],'backup_verified':True,'restore_verified':True,'image_sha256':hashlib.sha256(image.read_bytes()).hexdigest(),'ota_pair':{'qualification':{'frozen_path':str(evidence),'sha256':hashlib.sha256(evidence.read_bytes()).hexdigest()},'main':{'sha256':'1'*64},'recovery':{'sha256':'2'*64}}}
 (tmp_path/'plan.json').write_text(json.dumps(plan))
 code="import runpy,json;from pathlib import Path;p=runpy.run_path("+repr(str(ROOT/'tools/firmware/provision_vimar.py'))+");d=Path("+repr(str(tmp_path))+");p['validate_flash_gate'](d,json.loads((d/'plan.json').read_text()),(1,2))"
 result=subprocess.run([sys.executable,'-I','-c',code],cwd=tmp_path,capture_output=True,text=True)
 assert result.returncode==0,result.stderr


def test_no_implicit_legacy_release_or_probe(monkeypatch):
 import pytest,sys
 monkeypatch.delenv('VIMAR_OTA_RELEASE',raising=False)
 monkeypatch.setattr(sys,'argv',['provision_vimar.py','--serial','123'])
 monkeypatch.setattr(p,'detect',lambda *a:pytest.fail('Missing release must fail before hardware access'))
 with pytest.raises(SystemExit) as exc:p.main()
 assert exc.value.code==2


def test_backup_only_needs_no_release_and_never_prepares_or_flashes(tmp_path,monkeypatch):
 import sys
 monkeypatch.setattr(p,'KNOWN_DKS',{(0x11223344,0x55667788)})
 monkeypatch.setattr(p,'ROOT',tmp_path)
 monkeypatch.setattr(sys,'argv',['provision_vimar.py','--serial','123','--backup-only'])
 monkeypatch.setattr(p,'detect',lambda *a:(1,2))
 calls=[]
 def fake_backup(folder,uid,serial):
  calls.append((folder,uid,serial));(folder/'stock-flash-a.bin').write_bytes(b'stock')
 monkeypatch.setattr(p,'backup',fake_backup)
 monkeypatch.setattr(p,'prepare',lambda *a:__import__('pytest').fail('Backup must not build or program'))
 monkeypatch.setattr(p,'flash',lambda *a:__import__('pytest').fail('Backup must not program'))
 p.main()
 assert len(calls)==1 and calls[0][1:]==((1,2),'123')


def test_default_probe_serial_is_not_developer_specific(monkeypatch):
 import pytest,sys
 monkeypatch.delenv('VIMAR_JLINK_SERIAL',raising=False)
 monkeypatch.setattr(sys,'argv',['provision_vimar.py','--main','unused.hex','--prepare-only'])
 monkeypatch.setattr(p,'detect',lambda *a:pytest.fail('Missing probe must fail before hardware access'))
 with pytest.raises(SystemExit) as exc:p.main()
 assert exc.value.code==2


def test_ieee_is_corroborated_from_stock_bytes_without_network():
 uid=(0x12345678,0x9abcdef0)
 address=bytes.fromhex('f4ce36789abcdef0')[::-1]
 evidence=p.stock_ieee_evidence(uid,b'abc'+address+b'xyz'+address)
 assert evidence['candidate']=='0xf4ce36789abcdef0'
 assert evidence['stock_flash_little_endian_offsets']==[3,14]
 assert evidence['active_record_decoded'] is False
 assert p.stock_ieee_evidence(uid,b'other data')['stock_flash_little_endian_offsets']==[]

def test_split_flash_resume_cannot_reuse_only_legacy_checks(tmp_path):
 import pytest
 image=tmp_path/'initial-install.hex';image.write_text('prepared hex')
 checks={'main_sha256':'1'*64,'recovery_sha256':'2'*64,**{k:True for k in ['zigbee_ota_completed','postboot_hash_verified','ble_recovery_verified','power_cut_recovery_verified']}}
 evidence=tmp_path/'evidence.json';evidence.write_text(json.dumps(checks))
 plan={'uid':[1,2],'backup_verified':True,'restore_verified':True,'image_sha256':hashlib.sha256(image.read_bytes()).hexdigest(),'ota_pair':{'ota_profile':2,'qualification':{'frozen_path':str(evidence),'sha256':hashlib.sha256(evidence.read_bytes()).hexdigest()},'main':{'sha256':'1'*64},'recovery':{'sha256':'2'*64}}}
 with pytest.raises(ValueError,match='[Qq]ualification'):p.validate_flash_gate(tmp_path,plan,(1,2))
