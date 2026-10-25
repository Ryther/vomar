"""Qualified initial-install pair must preserve signed target/layout boundaries."""
import hashlib,json
from pathlib import Path
import pytest
from tools.firmware import ota_release
ROOT=Path(__file__).resolve().parents[3]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
@pytest.fixture
def release(tmp_path):
 evidence=tmp_path/'qualification.json'
 main=ROOT/'experiments/zigbee-ota-20261020/main-0.5.3-crypto-fixed.signed.bin';recovery=ROOT/'experiments/zigbee-ota-20261020/recovery-0.7.1.signed.bin'
 if not main.exists() or not recovery.exists():pytest.skip('Local frozen qualification artifacts required')
 evidence.write_text(json.dumps({'schema_version':1,'main_sha256':sha(main),'recovery_sha256':sha(recovery),**{k:True for k in ota_release.REQUIRED_CHECKS}}))
 data={'schema_version':1,'main':{'path':str(main),'sha256':sha(main),'version':'0.5.3+0'},'recovery':{'path':str(recovery),'sha256':sha(recovery),'version':'0.7.1+0'},'qualification':{'path':str(evidence),'sha256':sha(evidence)}}
 path=tmp_path/'pair.json';path.write_text(json.dumps(data));return path,data,evidence

def test_accepts_real_signed_pair_only_with_complete_qualification(release):
 path,data,_=release;pair=ota_release.load_ota_pair(path)
 assert pair['main']['data']==Path(data['main']['path']).read_bytes()
 assert pair['recovery']['data']==Path(data['recovery']['path']).read_bytes()
 assert pair['manifest_sha256']==sha(path)

def test_triple_pair_versions_preserve_minimum_and_signature_gate(release):
 path,data,_=release
 data['main']['version']='0.5.3';data['recovery']['version']='0.7.1'
 path.write_text(json.dumps(data));pair=ota_release.load_ota_pair(path)
 assert pair['main']['version']=='0.5.3+0' and pair['recovery']['version']=='0.7.1+0'

@pytest.mark.parametrize('missing',['zigbee_ota_completed','postboot_hash_verified','ble_recovery_verified','power_cut_recovery_verified'])
def test_incomplete_qualification_cannot_authorize_provisioning(release,missing):
 path,data,evidence=release;e=json.loads(evidence.read_text());e[missing]=False;evidence.write_text(json.dumps(e));data['qualification']['sha256']=sha(evidence);path.write_text(json.dumps(data))
 with pytest.raises(ValueError,match='qualification'):ota_release.load_ota_pair(path)

def test_modified_evidence_or_component_refuses_pair(release):
 path,data,evidence=release;evidence.write_text('{}')
 with pytest.raises(ValueError,match='SHA256'):ota_release.load_ota_pair(path)

def test_correctly_hashed_main_in_recovery_slot_is_rejected(release):
 path,data,evidence=release;data['recovery']=data['main'];checks=json.loads(evidence.read_text());checks['recovery_sha256']=data['main']['sha256'];evidence.write_text(json.dumps(checks));data['qualification']['sha256']=sha(evidence);path.write_text(json.dumps(data))
 with pytest.raises(ValueError,match='slot|size'):ota_release.load_ota_pair(path)

def test_version_claim_must_match_signed_header(release):
 path,data,_=release;data['main']['version']='9.9.9+0';path.write_text(json.dumps(data))
 with pytest.raises(ValueError,match='version'):ota_release.load_ota_pair(path)

def test_corrupted_but_rehashed_main_signature_is_rejected(release,tmp_path):
 path,data,evidence=release;blob=bytearray(Path(data['main']['path']).read_bytes());blob[600]^=1;bad=tmp_path/'corrupt.bin';bad.write_bytes(blob);data['main']['path']=str(bad);data['main']['sha256']=sha(bad);checks=json.loads(evidence.read_text());checks['main_sha256']=sha(bad);evidence.write_text(json.dumps(checks));data['qualification']['sha256']=sha(evidence);path.write_text(json.dumps(data))
 with pytest.raises(ValueError,match='signature'):ota_release.load_ota_pair(path)


def test_pair_does_not_accept_string_true_for_a_physical_check(release):
 path,data,evidence=release;e=json.loads(evidence.read_text());e['power_cut_recovery_verified']='true';evidence.write_text(json.dumps(e));data['qualification']['sha256']=sha(evidence);path.write_text(json.dumps(data))
 with pytest.raises(ValueError,match='qualification'):ota_release.load_ota_pair(path)


def test_qualification_cannot_be_reused_for_another_correctly_signed_image(release):
 path,data,_=release;other=ROOT/'experiments/zigbee-ota-20261020/main-0.5.3.signed.bin'
 if not other.exists():pytest.skip('Local superseded signed artifact required')
 data['main']['path']=str(other);data['main']['sha256']=sha(other);path.write_text(json.dumps(data))
 with pytest.raises(ValueError,match='qualification'):ota_release.load_ota_pair(path)

def test_profile2_cannot_reuse_legacy_qualification(release):
 path,data,evidence=release;data['ota_profile']=2;path.write_text(json.dumps(data))
 with pytest.raises(ValueError,match='split.*qualification'):ota_release.load_ota_pair(path)
