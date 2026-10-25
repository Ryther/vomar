"""Explicit signed qualification candidate; ordinary release APIs must reject it."""
import io,json,zipfile
import pytest
from test_common_v3_package import release3,save
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

def api():
 from tools.firmware.package_common_android_candidate import prepare_candidate_bundle,validate_candidate_bundle
 return prepare_candidate_bundle,validate_candidate_bundle

def pending(fixture):
 args,key,desc,blobs,q=fixture
 for field,value in list(q.items()):
  if isinstance(value,bool):q[field]=False
 q['stockRestoreVerified']=False
 path=args['release'].parent/'qualification.json';path.write_text(json.dumps(q))
 from tools.firmware.package_common_android_update import sha
 desc['qualification']['sha256']=sha(path.read_bytes());save(args,desc);return fixture

def test_explicit_candidate_retains_false_checks_and_default_qualified_paths_reject(release3):
 from tools.firmware.package_common_android_update_v3 import create_common_v3_bundle,validate_common_v3_bundle
 args,key,desc,blobs,q=pending(release3);prepare,validate=api()
 with pytest.raises(ValueError,match='qualification'):create_common_v3_bundle(**args)
 result=prepare(**args);raw=args['output'].read_bytes();verified=validate(raw,key.public_key())
 assert verified.purpose=='qualification-candidate' and verified.manifest['purpose']==verified.purpose
 assert all(v is False for k,v in verified.qualification.items() if isinstance(v,bool))
 with pytest.raises(ValueError):validate_common_v3_bundle(raw,key.public_key())
 with zipfile.ZipFile(io.BytesIO(raw)) as z:
  assert 'qualification.json' in z.namelist() and z.read('qualification.json')==(args['release'].parent/'qualification.json').read_bytes()
 assert result['hardware_qualified'] is False and result['qualified_release'] is False
 mutated=verified.manifest;mutated['purpose']='qualified';assert verified.manifest['purpose']=='qualification-candidate'
 with pytest.raises(ValueError):prepare(**args)

@pytest.mark.parametrize('damage',['passedflag','missingflag','extraflag','wrongcomponents','wrongcontracts'])
def test_candidate_requires_exact_hash_bound_all_false_report(release3,damage):
 from tools.firmware.package_common_android_update import sha
 args,key,desc,blobs,q=pending(release3);prepare,_=api()
 if damage=='passedflag':q['commonFirstFlashVerified']=True
 if damage=='missingflag':del q['stockRestoreVerified']
 if damage=='extraflag':q['pretendChecked']=False
 if damage=='wrongcomponents':q['components']['main']='00'*32
 if damage=='wrongcontracts':q['loaderContracts']=[]
 path=args['release'].parent/'qualification.json';path.write_text(json.dumps(q));desc['qualification']['sha256']=sha(path.read_bytes());save(args,desc)
 with pytest.raises(ValueError):prepare(**args)
 assert not args['output'].exists()

@pytest.mark.parametrize('damage',['purpose','qualification','signature','extra'])
def test_signed_or_unsigned_candidate_confusion_fails(release3,damage):
 from tools.firmware.package_common_android_update import canonical,sha
 args,key,*_=pending(release3);prepare,validate=api();prepare(**args)
 with zipfile.ZipFile(args['output']) as z:entries={n:z.read(n) for n in z.namelist()}
 manifest=json.loads(entries['manifest.json'])
 if damage=='purpose':manifest['purpose']='qualified'
 elif damage=='qualification':
  q=json.loads(entries['qualification.json']);q['power_cut_recovery_verified']=True;entries['qualification.json']=canonical(q);manifest['qualificationSha256']=sha(entries['qualification.json'])
 elif damage=='extra':entries['approval.json']=b'{}'
 elif damage=='signature':entries['manifest.sig']=b'bad'
 if damage in ('purpose','qualification'):
  del manifest['bundleId'];manifest['bundleId']=sha(canonical(manifest));entries['manifest.json']=canonical(manifest);entries['manifest.sig']=key.sign(entries['manifest.json'],ec.ECDSA(hashes.SHA256()))
 out=io.BytesIO()
 with zipfile.ZipFile(out,'w') as z:
  for n,v in entries.items():z.writestr(n,v)
 with pytest.raises(ValueError):validate(out.getvalue(),key.public_key())


def test_shared_validation_has_no_undefined_empty_mode_that_skips_qualification(release3):
 from tools.firmware.package_common_android_update_v3 import create_common_v3_bundle,_validate_common_v3_bundle
 args,key,*_=release3;create_common_v3_bundle(**args)
 with zipfile.ZipFile(args['output']) as z:entries={n:z.read(n) for n in z.namelist()}
 entries['qualification.json']=b'not a checked report'
 output=io.BytesIO()
 with zipfile.ZipFile(output,'w') as z:
  for name,data in entries.items():z.writestr(name,data)
 with pytest.raises(ValueError):_validate_common_v3_bundle(output.getvalue(),key.public_key(),expected_purpose='')


def test_watchdog_candidate_remains_explicit_all_false_and_default_rejected(release3):
 from tools.firmware.package_common_android_update_v3 import validate_common_v3_bundle
 args,key,desc,_,_=pending(release3);prepare,validate=api()
 desc['watchdogHandoff']='paused-reset-before-main-v1';save(args,desc);prepare(**args)
 raw=args['output'].read_bytes();verified=validate(raw,key.public_key())
 assert verified.purpose=='qualification-candidate'
 assert all(v is False for v in verified.qualification.values() if isinstance(v,bool))
 with zipfile.ZipFile(io.BytesIO(raw)) as archive:
  assert json.loads(archive.read('first-install.json'))['watchdogHandoff']=='paused-reset-before-main-v1'
 assert 'watchdogHandoff' not in verified.manifest
 with pytest.raises(ValueError):validate_common_v3_bundle(raw,key.public_key())


@pytest.mark.parametrize('policy',[None,'paused-reset-before-main-v2',True])
def test_candidate_unknown_watchdog_policy_never_publishes(release3,policy):
 args,_,desc,_,_=pending(release3);prepare,_=api();desc['watchdogHandoff']=policy;save(args,desc)
 with pytest.raises(ValueError):prepare(**args)
 assert not args['output'].exists()
