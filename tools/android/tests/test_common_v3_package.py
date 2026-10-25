"""Isolated schema3 ONE-ZIP producer/reference validator: ephemeral test keys only."""
import hashlib,json,struct,zipfile,io
from pathlib import Path
import pytest
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from test_common_update_package import signed_image,sha

def api():
 from tools.firmware.package_common_android_update_v3 import create_common_v3_bundle,validate_common_v3_bundle
 return create_common_v3_bundle,validate_common_v3_bundle

@pytest.fixture
def release3(tmp_path):
 from tools.firmware.ota_release import REQUIRED_CHECKS,SPLIT_REQUIRED_CHECKS
 from tools.firmware.loader_runtime_contract import measure_record,COMMON_KIND
 key=ec.generate_private_key(ec.SECP256R1());public=key.public_key()
 private_path=tmp_path/'ephemeral.pem';private_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
 public_path=tmp_path/'public.pem';public_path.write_bytes(public.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
 # Header/payload use slot1 vectors for recovery before signing.
 def image(role):
  if role==1:return signed_image(key)
  raw=bytearray(signed_image(key,role=role));struct.pack_into('<I',raw,516,0xb0201)
  from tools.firmware.package_zigbee_ota import image as parse
  old=parse(bytes(raw));end=old['authenticated_end'];region=bytes(raw[:end]);digest=hashlib.sha256(region).digest();sig=key.sign(digest,ec.ECDSA(__import__('cryptography').hazmat.primitives.asymmetric.utils.Prehashed(hashes.SHA256())))
  keyhash=old['unprotected'][1];fields=b''.join(struct.pack('<HH',t,len(v))+v for t,v in [(1,keyhash),(0x10,digest),(0x22,sig)])
  return region+struct.pack('<HH',0x6907,len(fields)+4)+fields
 loader=struct.pack('<II',0x20010000,0x101)+b'\x00'*(0xb000-8)+b'\xff'*0x1000
 blobs={'loader':loader,'main':image(1),'recovery':image(2)}
 records=[measure_record(loader,COMMON_KIND).as_dict(),dict(kind='legacy-full48k-sha256',sha256='ab'*32)]
 desc=dict(schemaVersion=3,minAppVersion='0.6.0',model='VIMAR30805',layoutVersion=2,identityProtocol=2,loaderContracts=records,legacyRecoverySignedHashes=[],allowedSourceSignedHashes=['cd'*32])
 from tools.firmware.package_common_android_update import verify_component
 desc['targetRecoverySignedHash']=verify_component(blobs['recovery'],public,'recovery')['signedRegionSha256']
 for name,blob in blobs.items():
  path=tmp_path/(name+'.bin');path.write_bytes(blob);desc[name]=dict(path=path.name,sha256=sha(blob))
 qualification=dict(schemaVersion=3,model='VIMAR30805',layoutVersion=2,loaderContracts=records,components={k:sha(v) for k,v in blobs.items()},commonFirstFlashVerified=True,**{f:True for f in (*REQUIRED_CHECKS,*SPLIT_REQUIRED_CHECKS)})
 qpath=tmp_path/'qualification.json';qpath.write_text(json.dumps(qualification));desc['qualification']=dict(path=qpath.name,sha256=sha(qpath.read_bytes()))
 path=tmp_path/'release.json';path.write_text(json.dumps(desc))
 return dict(release=path,output=tmp_path/'one-common.zip',private_key=private_path,public_key=public_path),key,desc,blobs,qualification

def save(args,desc):args['release'].write_text(json.dumps(desc))

def test_one_zip_binds_inner_template_and_outer_update_contracts(release3):
 args,key,desc,blobs,q=release3;build,validate=api();result=build(**args)
 manifest=validate(args['output'].read_bytes(),key.public_key())
 assert result['bundleId']==manifest['bundleId'] and manifest['schemaVersion']==3 and manifest['identityProtocol']==2
 with zipfile.ZipFile(args['output']) as z:
  assert set(z.namelist())=={'manifest.json','manifest.sig','main.signed.bin','recovery.signed.bin','loader.bin','first-install.json','first-install.sig'}
  first=json.loads(z.read('first-install.json'))
  assert first['loaderContracts']==desc['loaderContracts'][:1]
  assert first['images']['loader']==dict(file='loader.bin',size=49152,sha256=sha(blobs['loader']))
  assert first['images']['main']['sha256']==manifest['main']['fileSha256'] and 'wireVersion' not in first['images']['main']
  key.public_key().verify(z.read('first-install.sig'),z.read('first-install.json'),ec.ECDSA(hashes.SHA256()))
 assert 'allowedLoaderSha256' not in manifest
 with pytest.raises(ValueError):build(**args)

@pytest.mark.parametrize('change',['unknown-field','identity-downgrade','legacy-untyped','unsorted','family-not-approved','rec-file-vs-signed','loader-anchor','loader-vector','qualification-false','qualification-contract','qualification-component','stock-unpaired','main-role'])
def test_bad_authority_or_artifacts_never_publish(release3,change):
 args,key,desc,blobs,q=release3;build,_=api()
 if change=='unknown-field':desc['mask']=0xb000
 elif change=='identity-downgrade':desc['identityProtocol']=1
 elif change=='legacy-untyped':desc['allowedLoaderSha256']=['00'*32]
 elif change=='unsorted':desc['loaderContracts'].reverse()
 elif change=='family-not-approved':desc['loaderContracts'][0]['sha256']='00'*32
 elif change=='rec-file-vs-signed':desc['targetRecoverySignedHash']=sha(blobs['recovery'])
 elif change in ('loader-anchor','loader-vector'):
  blob=bytearray(blobs['loader']);blob[0xb000 if change=='loader-anchor' else 4]^=2;p=args['release'].parent/'loader.bin';p.write_bytes(blob);desc['loader']['sha256']=sha(blob)
 elif change.startswith('qualification'):
  if change=='qualification-false':q['commonFirstFlashVerified']=False
  if change=='qualification-contract':q['loaderContracts']=[]
  if change=='qualification-component':q['components']['loader']='00'*32
  p=args['release'].parent/'qualification.json';p.write_text(json.dumps(q));desc['qualification']['sha256']=sha(p.read_bytes())
 elif change=='stock-unpaired':desc['stockRestore']=desc['recovery']
 elif change=='main-role':desc['main']=desc['recovery']
 save(args,desc)
 with pytest.raises(ValueError):build(**args)
 assert not args['output'].exists()

@pytest.mark.parametrize('mutation',['extra','duplicate','component','inner','inner-signature','outer-signature','kind','wire-bool'])
def test_reference_validator_rejects_archive_or_signature_confusion(release3,mutation):
 args,key,desc,blobs,q=release3;build,validate=api();build(**args)
 with zipfile.ZipFile(args['output']) as z:entries={n:z.read(n) for n in z.namelist()}
 if mutation=='extra':entries['private-identity.json']=b'{}'
 elif mutation=='component':entries['recovery.signed.bin']=entries['main.signed.bin']
 elif mutation=='inner':
  inner=json.loads(entries['first-install.json']);inner['images']['main']['role']='MIGRATION';entries['first-install.json']=(json.dumps(inner,sort_keys=True,separators=(',',':'))+'\n').encode();entries['first-install.sig']=key.sign(entries['first-install.json'],ec.ECDSA(hashes.SHA256()))
 elif mutation=='wire-bool':
  m=json.loads(entries['manifest.json']);m['main']['wireVersion'][0]=False;entries['manifest.json']=(json.dumps(m,sort_keys=True,separators=(',',':'))+'\n').encode()
 elif mutation=='kind':
  m=json.loads(entries['manifest.json']);m['loaderContracts'][0]['kind']='legacy-full48k-sha256';entries['manifest.json']=(json.dumps(m,sort_keys=True,separators=(',',':'))+'\n').encode();entries['manifest.sig']=key.sign(entries['manifest.json'],ec.ECDSA(hashes.SHA256()))
 elif mutation=='inner-signature':entries['first-install.sig']=entries['first-install.sig'][:-1]+b'\x00'
 elif mutation=='outer-signature':entries['manifest.sig']=b'bad'
 if mutation in ('inner','kind','wire-bool'):
  m=json.loads(entries['manifest.json'])
  if mutation=='inner':m['firstInstall'].update(size=len(entries['first-install.json']),sha256=sha(entries['first-install.json']),signatureSha256=sha(entries['first-install.sig']))
  del m['bundleId'];m['bundleId']=sha((json.dumps(m,sort_keys=True,separators=(',',':'))+'\n').encode());entries['manifest.json']=(json.dumps(m,sort_keys=True,separators=(',',':'))+'\n').encode();entries['manifest.sig']=key.sign(entries['manifest.json'],ec.ECDSA(hashes.SHA256()))
 out=io.BytesIO()
 with zipfile.ZipFile(out,'w') as z:
  for n,v in entries.items():z.writestr(n,v)
  if mutation=='duplicate':z.writestr('loader.bin',blobs['loader'])
 with pytest.raises(ValueError):validate(out.getvalue(),key.public_key())


def test_role4_uses_reviewed_63page_slot_while_role2_remains_split34000(release3):
 from tools.firmware.package_common_android_update_v3 import verify_image
 from tools.firmware.package_zigbee_ota import image
 from cryptography.hazmat.primitives.asymmetric import utils
 args,key,_,blobs,_=release3
 def enlarged(role,size):
  ordinary=bytearray(blobs['recovery']);parsed=image(bytes(ordinary));fields=struct.pack('<HH',0xa0,11)+b'VIMAR30805\x02'+struct.pack('<HHB',0xa1,1,role);prot=struct.pack('<HH',0x6908,len(fields)+4)+fields
  payload=bytes(ordinary[512:576])+bytes(size-64);head=ordinary[:512];struct.pack_into('<HI',head,10,len(prot),size)
  region=bytes(head)+payload+prot;digest=hashlib.sha256(region).digest();signature=key.sign(digest,ec.ECDSA(utils.Prehashed(hashes.SHA256())))
  entries=b''.join(struct.pack('<HH',tag,len(value))+value for tag,value in [(1,parsed['unprotected'][1]),(0x10,digest),(0x22,signature)])
  return region+struct.pack('<HH',0x6907,len(entries)+4)+entries
 blob=enlarged(4,0x35000)
 assert 0x34000<len(blob)<0x3f000
 assert verify_image(blob,key.public_key(),'stockRestore')['role']=='RESTORE'
 with pytest.raises(ValueError):verify_image(enlarged(2,0x35000),key.public_key(),'recovery')
 with pytest.raises(ValueError):verify_image(enlarged(4,0x3f000),key.public_key(),'stockRestore')


def test_optional_migration_carrier_and_stock_pair_share_one_zip(release3):
 from test_common_update_package import attach_ota
 from tools.firmware.package_zigbee_ota import image
 from cryptography.hazmat.primitives.asymmetric import utils
 args,key,desc,blobs,q=release3;build,validate=api()
 def helper(role,slot1):
  blob=bytearray(signed_image(key,role=role))
  if slot1:struct.pack_into('<I',blob,516,0xb0201)
  parsed=image(bytes(blob));region=bytes(blob[:parsed['authenticated_end']]);digest=hashlib.sha256(region).digest();sig=key.sign(digest,ec.ECDSA(utils.Prehashed(hashes.SHA256())))
  fields=b''.join(struct.pack('<HH',tag,len(value))+value for tag,value in [(1,parsed['unprotected'][1]),(0x10,digest),(0x22,sig)])
  return region+struct.pack('<HH',0x6907,len(fields)+4)+fields
 for name,role,slot1 in [('migration',3,False),('stockRestore',4,True),('stockBootstrap',3,False)]:
  blob=helper(role,slot1);path=args['release'].parent/(name+'.bin');path.write_bytes(blob);desc[name]=dict(path=path.name,sha256=sha(blob));q['components'][name]=sha(blob)
 desc['legacyRecoverySignedHashes']=['ef'*32];q['stockRestoreVerified']=True
 path=args['release'].parent/'qualification.json';path.write_text(json.dumps(q));desc['qualification']['sha256']=sha(path.read_bytes());save(args,desc)
 (args['release'].parent/'main.signed.bin').write_bytes(blobs['main']);attach_ota(args,key)
 build(**args);manifest=validate(args['output'].read_bytes(),key.public_key())
 with zipfile.ZipFile(args['output']) as z:assert len(z.namelist())==11
 assert manifest['stockRestore']['role']=='RESTORE' and manifest['stockBootstrap']['role']=='MIGRATION' and manifest['zigbeeOta']['mainSignedRegionSha256']==manifest['main']['signedRegionSha256']


def test_watchdog_handoff_is_signed_inner_capability_and_outer_hash_bound(release3):
 args,key,desc,_,_=release3;build,validate=api()
 desc['watchdogHandoff']='paused-reset-before-main-v1';save(args,desc);build(**args)
 manifest=validate(args['output'].read_bytes(),key.public_key())
 with zipfile.ZipFile(args['output']) as archive:
  raw=archive.read('first-install.json');first=json.loads(raw)
  assert first['watchdogHandoff']=='paused-reset-before-main-v1'
  assert manifest['firstInstall']['sha256']==sha(raw)
  assert 'watchdogHandoff' not in manifest


def test_absent_watchdog_handoff_remains_absent_for_legacy_inactive_only_descriptor(release3):
 args,key,_,_,_=release3;build,validate=api();build(**args)
 validate(args['output'].read_bytes(),key.public_key())
 with zipfile.ZipFile(args['output']) as archive:
  assert 'watchdogHandoff' not in json.loads(archive.read('first-install.json'))


@pytest.mark.parametrize('policy',['',None,False,1,{},'run-on-halt','paused-reset-before-main-v2'])
def test_unknown_input_watchdog_policy_rejected_before_output(release3,policy):
 args,_,desc,_,_=release3;build,_=api();desc['watchdogHandoff']=policy;save(args,desc)
 with pytest.raises(ValueError):build(**args)
 assert not args['output'].exists()


def watchdog_archive(entries):
 output=io.BytesIO()
 with zipfile.ZipFile(output,'w') as archive:
  for name,blob in entries.items():archive.writestr(name,blob)
 return output.getvalue()


def resign_watchdog_archive(entries,key,*,bind_inner):
 from tools.firmware.package_common_android_update import canonical
 if bind_inner:
  entries['first-install.sig']=key.sign(entries['first-install.json'],ec.ECDSA(hashes.SHA256()))
 manifest=json.loads(entries['manifest.json'])
 manifest['firstInstall'].update(size=len(entries['first-install.json']),sha256=sha(entries['first-install.json']),signatureSha256=sha(entries['first-install.sig']))
 del manifest['bundleId'];manifest['bundleId']=sha(canonical(manifest))
 entries['manifest.json']=canonical(manifest);entries['manifest.sig']=key.sign(entries['manifest.json'],ec.ECDSA(hashes.SHA256()))


@pytest.mark.parametrize('mutation',['unsigned-inner','unsigned-outer','unknown-signed','null-signed','outer-only','loader-family'])
def test_watchdog_capability_requires_inner_signature_outer_binding_and_exact_loader(release3,mutation):
 from tools.firmware.package_common_android_update import canonical
 args,key,desc,_,_=release3;build,validate=api()
 desc['watchdogHandoff']='paused-reset-before-main-v1';save(args,desc);build(**args)
 with zipfile.ZipFile(args['output']) as archive:entries={n:archive.read(n) for n in archive.namelist()}
 first=json.loads(entries['first-install.json'])
 if mutation in ('unsigned-inner','unsigned-outer'):
  del first['watchdogHandoff'];entries['first-install.json']=canonical(first)
  if mutation=='unsigned-inner':resign_watchdog_archive(entries,key,bind_inner=False)
  else:entries['first-install.sig']=key.sign(entries['first-install.json'],ec.ECDSA(hashes.SHA256()))
 elif mutation in ('unknown-signed','null-signed'):
  first['watchdogHandoff']='invented' if mutation=='unknown-signed' else None
  entries['first-install.json']=canonical(first);resign_watchdog_archive(entries,key,bind_inner=True)
 elif mutation=='outer-only':
  manifest=json.loads(entries['manifest.json']);manifest['watchdogHandoff']='paused-reset-before-main-v1'
  del manifest['bundleId'];manifest['bundleId']=sha(canonical(manifest))
  entries['manifest.json']=canonical(manifest);entries['manifest.sig']=key.sign(entries['manifest.json'],ec.ECDSA(hashes.SHA256()))
 elif mutation=='loader-family':
  first['loaderContracts'][0]['sha256']='00'*32;entries['first-install.json']=canonical(first)
  resign_watchdog_archive(entries,key,bind_inner=True)
 with pytest.raises(ValueError):validate(watchdog_archive(entries),key.public_key())
