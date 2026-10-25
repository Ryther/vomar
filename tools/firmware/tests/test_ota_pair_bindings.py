"""Pair header creation validates real device-bound restoration authorizations."""
from local_inputs import local_input, sdk_root
import hashlib,json
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[3]
def manifest(tmp_path):
 def source(path):
  path=local_input(path)
  return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
 base=ROOT/'experiments/zigbee-ota-migration-20261020'
 d={'schema_version':1,'audited_loader_config':source(ROOT/'work/build-vimar-loader-ldo-debounce/mcuboot/zephyr/.config'),
 'loader_authorizations':[{'manifest':source(base/'scrivania-manifest.json'),'recovery':source(base/'scrivania-fixed-v2/recovery-0.7.1.signed.bin')}]}
 p=tmp_path/'source.json';p.write_text(json.dumps(d));return p,d

def test_pair_header_pins_loader_after_validating_restore_and_actual_raw_bytes(tmp_path):
 from tools.firmware.build_ota_pair_bindings import prepare_pair_bindings
 p,d=manifest(tmp_path);r=prepare_pair_bindings(p,tmp_path/'out')
 report=json.loads(Path(r['report_path']).read_text())
 assert report['allowed_loaders']==['25b56199cbc9f6a7096bbbf9f88dbdce5201c5ea88bd8354ac5c3bd0aeff83c0']
 assert report['recovery_sha256'] is None and report['hardware_qualified'] is False
 assert Path(r['header_path']).is_file()

@pytest.mark.parametrize('damage',['manifest_hash','config_hash','empty_allowlist'])
def test_pair_header_rejects_unverifiable_authorization(tmp_path,damage):
 from tools.firmware.build_ota_pair_bindings import prepare_pair_bindings
 p,d=manifest(tmp_path)
 if damage=='manifest_hash':d['loader_authorizations'][0]['manifest']['sha256']='00'*32
 if damage=='config_hash':d['audited_loader_config']['sha256']='00'*32
 if damage=='empty_allowlist':d['loader_authorizations']=[]
 p.write_text(json.dumps(d))
 with pytest.raises(ValueError):prepare_pair_bindings(p,tmp_path/'out')
 assert not (tmp_path/'out').exists()


from test_image_roles import crypto


def role_recovery_manifest(tmp_path, crypto, monkeypatch):
 from test_image_roles import fixture
 from cryptography.hazmat.primitives import serialization
 from tools.firmware import build_ota_pair_bindings as builder
 p,data=manifest(tmp_path)
 public=tmp_path/'ephemeral-public.pem'
 public.write_bytes(crypto[1].public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
 monkeypatch.setattr(builder,'PUBLIC_KEY',public)
 recovery,_=fixture(crypto,role=b'\x02',version=(0,8,0,0),vector_base=0xb0000)
 signed=tmp_path/'recovery.bin';signed.write_bytes(recovery)
 def record(path):return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
 data.update(recovery_signed=record(signed),recovery_version='0.8.0',
  recovery_config=record(local_input(ROOT/'experiments/bluetooth-service-20261023-v4/build/zephyr/.config')))
 p.write_text(json.dumps(data))
 return builder,p,data,signed


def test_explicit_new_recovery_version_requires_authenticated_role_and_keeps_gates(tmp_path,crypto,monkeypatch):
 builder,p,data,signed=role_recovery_manifest(tmp_path,crypto,monkeypatch)
 result=builder.prepare_pair_bindings(p,tmp_path/'out')
 report=json.loads(Path(result['report_path']).read_text())
 assert report['recovery_sha256']==hashlib.sha256(signed.read_bytes()).hexdigest()
 assert report['recovery_version']=='0.8.0'
 assert report['hardware_qualified'] is False


@pytest.mark.parametrize('damage',['version','role','profile','signature','config','positive_build'])
def test_new_recovery_binding_rejects_wrong_role_version_signature_and_config(tmp_path,crypto,monkeypatch,damage):
 from test_image_roles import fixture
 builder,p,data,signed=role_recovery_manifest(tmp_path,crypto,monkeypatch)
 if damage in ['role','profile']:
  ordinary,_=fixture(crypto,role=b'\x03' if damage=='role' else b'\x02',
    target=b'VIMAR30805\x01' if damage=='profile' else b'VIMAR30805\x02',version=(0,8,0,0),vector_base=0xb0000)
  signed.write_bytes(ordinary)
 if damage=='version':data['recovery_version']='0.8.1'
 if damage=='positive_build':data['recovery_version']='0.8.0+1'
 if damage=='signature':
  blob=bytearray(signed.read_bytes());blob[-1]^=1;signed.write_bytes(blob)
 if damage=='config':
  config=tmp_path/'bad.config';config.write_text('CONFIG_VIMAR_OTA_SPLIT_STAGING=y\n')
  data['recovery_config']=dict(path=str(config),sha256=hashlib.sha256(config.read_bytes()).hexdigest())
 data['recovery_signed']['sha256']=hashlib.sha256(signed.read_bytes()).hexdigest();p.write_text(json.dumps(data))
 with pytest.raises(ValueError):builder.prepare_pair_bindings(p,tmp_path/'out')
 assert not (tmp_path/'out').exists()
