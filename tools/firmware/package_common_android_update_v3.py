#!/usr/bin/env python3
"""Isolated schema3 ONE common ZIP producer/reference validator.

Not wired into the frozen Android consumer or legacy schema2 producer. Explicit
ECDSA P256 key paths only; qualification is required before release output.
No hardware I/O, per-device identity, private original backup or anchor is read.
"""
import argparse,hashlib,io,json,re,struct,zipfile,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec,utils
from tools.firmware.package_common_android_update import canonical,sha,digest,hashes_list,verify_zigbee_carrier
from tools.firmware.package_android_update import MAX_ZIP,MAX_IMAGE,signed_metadata
from tools.firmware.build_ota_migration import check_slot
from tools.firmware.ota_release import REQUIRED_CHECKS,SPLIT_REQUIRED_CHECKS
from tools.firmware.loader_runtime_contract import validate_records,measure_record,COMMON_KIND,LOADER_SIZE,CODE_SIZE
ROOT=Path(__file__).resolve().parents[2]
ROLES={'main':1,'recovery':2,'migration':3,'stockRestore':4,'stockBootstrap':3}
FILES={'main':'main.signed.bin','recovery':'recovery.signed.bin','migration':'migration.signed.bin','stockRestore':'stock-restore.signed.bin','stockBootstrap':'stock-bootstrap.signed.bin'}
BASE={'schemaVersion','minAppVersion','model','layoutVersion','identityProtocol','loaderContracts','legacyRecoverySignedHashes','targetRecoverySignedHash','allowedSourceSignedHashes','main','recovery'}
OPTIONAL={'migration','zigbeeOta','stockRestore','stockBootstrap'}
WATCHDOG_HANDOFF='paused-reset-before-main-v1'
INPUT_OPTIONAL=OPTIONAL|{'watchdogHandoff'}
OUTER_REQUIRED=BASE|{'bundleId','qualificationSha256','firstInstall'}
IMAGE_FIELDS={'file','size','version','wireVersion','fileSha256','signedRegionSha256','role'}
FIRST_META={'file','size','sha256','signatureFile','signatureSha256'}

def exact(value,required,optional=()):
 if type(value) is not dict or not required<=set(value) or set(value)-required-set(optional):raise ValueError('unknown or missing contract fields')

def strict_json(raw):
 def pairs(entries):
  result={}
  for k,v in entries:
   if k in result:raise ValueError('duplicate JSON field')
   result[k]=v
  return result
 try:value=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('invalid number')))
 except (UnicodeError,json.JSONDecodeError) as exc:raise ValueError('invalid JSON') from exc
 return value

def common_fields(value):
 if any(type(value.get(k)) is not int or value[k]!=v for k,v in [('schemaVersion',3),('layoutVersion',2),('identityProtocol',2)]) or value.get('model')!='VIMAR30805':raise ValueError('unsupported schema3 contract')
 if type(value.get('minAppVersion')) is not str or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)',value['minAppVersion']):raise ValueError('invalid app SemVer')
 validate_records(value['loaderContracts'])
 for field in ('legacyRecoverySignedHashes','allowedSourceSignedHashes'):hashes_list(value[field],empty=field=='legacyRecoverySignedHashes')
 digest(value['targetRecoverySignedHash'])
 if bool(value['legacyRecoverySignedHashes'])!=('migration' in value):raise ValueError('explicit legacy REC list and MIG must occur together')
 if ('stockRestore' in value)!=('stockBootstrap' in value):raise ValueError('stock RESTORE/bootstrap must occur together')

def load_public_key(value):
 key=serialization.load_pem_public_key(Path(value).read_bytes()) if isinstance(value,(Path,str)) else value
 if not isinstance(key,ec.EllipticCurvePublicKey) or not isinstance(key.curve,ec.SECP256R1):raise ValueError('ECDSA P256 public key required')
 return key

def verify_signature(key,signature,data):
 if not 8<=len(signature)<=80:raise ValueError('signature length outside DER bound')
 try:key.verify(signature,data,ec.ECDSA(hashes.SHA256()))
 except (ValueError,InvalidSignature) as exc:raise ValueError('invalid signature') from exc

def verify_image(blob,key,name):
 role=ROLES[name];slot1=name in ('recovery','stockRestore')
 parsed=check_slot(blob,0xb0000 if slot1 else 0xc000,(0x3f000 if name=='stockRestore' else 0x34000) if slot1 else 0xa2000)
 if len(blob)>MAX_IMAGE or parsed['flags'] or struct.unpack_from('<I',blob,4)[0] or struct.unpack_from('<I',blob,28)[0]:raise ValueError('ordinary signed image required')
 prot=parsed['protected'];unprot=parsed['unprotected']
 if prot.get(0xa0)!=b'VIMAR30805\x02' or prot.get(0xa1)!=bytes([role]) or set(prot)-{0x50,0xa0,0xa1} or (0x50 in prot and len(prot[0x50])!=4):raise ValueError('protected image role/profile mismatch')
 keyhash=hashlib.sha256(key.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).digest();signed=hashlib.sha256(blob[:parsed['authenticated_end']]).digest()
 if set(unprot)!={1,0x10,0x22} or unprot[1]!=keyhash or unprot[0x10]!=signed:raise ValueError('image key/hash/TLV mismatch')
 try:key.verify(unprot[0x22],signed,ec.ECDSA(utils.Prehashed(hashes.SHA256())))
 except (ValueError,InvalidSignature) as exc:raise ValueError('invalid image signature') from exc
 return dict(signed_metadata(blob,FILES[name]),role={1:'MAIN',2:'RECOVERY',3:'MIGRATION',4:'RESTORE'}[role])

def loader_descriptor(loader,contracts):
 if len(loader)!=LOADER_SIZE or loader[CODE_SIZE:]!=b'\xff'*4096:raise ValueError('exact48KiB loader with FF anchor placeholder required')
 stack,reset=struct.unpack_from('<II',loader)
 if stack<=0x20000000 or stack>0x20040000 or stack%8 or not reset&1 or not 8<=reset&~1<CODE_SIZE:raise ValueError('loader vectors outside fixed code/RAM contract')
 record=measure_record(loader,COMMON_KIND).as_dict()
 if record not in contracts:raise ValueError('template code family is not explicitly approved')
 return record

def validate_watchdog_handoff(value):
 if type(value) is not str or value!=WATCHDOG_HANDOFF:raise ValueError('unsupported watchdog handoff')
 return value

def first_descriptor(loader,metadata,contracts,watchdog_handoff=None):
 descriptor=dict(schemaVersion=1,type='vimar30805-common-first-install',model='VIMAR30805',layoutVersion=2,identityProtocol=2,
  loaderContracts=[loader_descriptor(loader,contracts)],images={'loader':dict(file='loader.bin',size=LOADER_SIZE,sha256=sha(loader)),**{name:dict(file=m['file'],size=m['size'],sha256=m['fileSha256'],signedRegionSha256=m['signedRegionSha256'],role=m['role'],version=m['version']) for name,m in metadata.items() if name in ('main','recovery')}})
 if watchdog_handoff is not None:descriptor['watchdogHandoff']=validate_watchdog_handoff(watchdog_handoff)
 return descriptor

def entries_for(manifest,qualification=False):
 entries={'manifest.json','manifest.sig','loader.bin','first-install.json','first-install.sig'}|{FILES[n] for n in ROLES if n in manifest}
 if 'zigbeeOta' in manifest:entries.add('main.ota')
 if qualification:entries.add('qualification.json')
 return entries

def _validate_common_v3_bundle(raw,key,expected_purpose=None):
 if expected_purpose not in (None,"qualification-candidate"):raise ValueError("undefined release validation mode")
 key=load_public_key(key)
 if type(raw) is not bytes or not 1<=len(raw)<=MAX_ZIP:raise ValueError('bounded ZIP required')
 try:
  with zipfile.ZipFile(io.BytesIO(raw)) as archive:
   info=archive.infolist();names=[v.filename for v in info]
   if len(names)!=len(set(names)) or len(names)>(12 if expected_purpose else 11) or any(v.file_size<0 or v.file_size>MAX_IMAGE or v.flag_bits&1 or v.is_dir() for v in info) or sum(v.file_size for v in info)>MAX_ZIP:raise ValueError('duplicate/oversized/encrypted ZIP entries')
   entries={n:archive.read(n) for n in names}
 except (zipfile.BadZipFile,RuntimeError,NotImplementedError) as exc:raise ValueError('invalid ZIP') from exc
 if not {'manifest.json','manifest.sig'}<=set(entries):raise ValueError('missing signed manifest')
 mraw=entries['manifest.json']
 if len(mraw)>65536:raise ValueError('manifest too large')
 verify_signature(key,entries['manifest.sig'],mraw);manifest=strict_json(mraw)
 exact(manifest,OUTER_REQUIRED|({"purpose"} if expected_purpose else set()),OPTIONAL);common_fields(manifest)
 if expected_purpose and manifest["purpose"]!=expected_purpose:raise ValueError("unsupported candidate purpose")
 if canonical(manifest)!=mraw:raise ValueError('noncanonical manifest')
 digest(manifest['bundleId']);identity={k:v for k,v in manifest.items() if k!='bundleId'}
 if sha(canonical(identity))!=manifest['bundleId']:raise ValueError('bundle ID mismatch')
 digest(manifest['qualificationSha256'])
 if set(entries)!=entries_for(manifest,qualification=expected_purpose is not None):raise ValueError('unknown or missing ZIP entries')
 metadata={name:verify_image(entries[FILES[name]],key,name) for name in ROLES if name in manifest}
 for name,actual in metadata.items():
  exact(manifest[name],IMAGE_FIELDS)
  if canonical(manifest[name])!=canonical(actual):raise ValueError('signed image metadata mismatch')
 if metadata['recovery']['signedRegionSha256']!=manifest['targetRecoverySignedHash']:raise ValueError('target REC signed-region mismatch')
 if 'zigbeeOta' in manifest:
  actual=verify_zigbee_carrier(entries['main.ota'],entries[FILES['main']],key,metadata['main'])
  if canonical(manifest['zigbeeOta'])!=canonical(actual):raise ValueError('carrier metadata mismatch')
 f=manifest['firstInstall'];exact(f,FIRST_META)
 if f['file']!='first-install.json' or f['signatureFile']!='first-install.sig' or type(f['size']) is not int or not 1<=f['size']<=65536:raise ValueError('invalid installer reference')
 first=entries['first-install.json'];signature=entries['first-install.sig']
 if len(first)!=f['size'] or sha(first)!=digest(f['sha256']) or sha(signature)!=digest(f['signatureSha256']):raise ValueError('installer reference hash mismatch')
 verify_signature(key,signature,first);descriptor=strict_json(first)
 handoff=validate_watchdog_handoff(descriptor['watchdogHandoff']) if type(descriptor) is dict and 'watchdogHandoff' in descriptor else None
 if canonical(descriptor)!=first or canonical(descriptor)!=canonical(first_descriptor(entries['loader.bin'],metadata,manifest['loaderContracts'],handoff)):raise ValueError('installer differs from outer image/family authority')
 if expected_purpose:
  qualification=entries['qualification.json']
  if len(qualification)>65536 or sha(qualification)!=manifest['qualificationSha256']:raise ValueError('candidate qualification hash mismatch')
  validate_pending_qualification(strict_json(qualification),manifest,{name:entries[FILES[name]] for name in metadata},entries['loader.bin'],entries.get('main.ota'))
 return manifest

def validate_pending_qualification(q,authority,components,loader,carrier):
 flags=set(REQUIRED_CHECKS)|set(SPLIT_REQUIRED_CHECKS)|{'commonFirstFlashVerified','stockRestoreVerified'}
 exact(q,{'schemaVersion','model','layoutVersion','loaderContracts','components'}|flags)
 if type(q['schemaVersion']) is not int or q['schemaVersion']!=3 or type(q['layoutVersion']) is not int or q['layoutVersion']!=2 or q['model']!='VIMAR30805' or any(q[k] is not False for k in flags):raise ValueError('candidate qualification requires every physical check literally false')
 expected={**{name:sha(blob) for name,blob in components.items()},'loader':sha(loader)}
 if carrier is not None:expected['zigbeeOta']=sha(carrier)
 if canonical(q['loaderContracts'])!=canonical(authority['loaderContracts']) or q['components']!=expected:raise ValueError('candidate qualification not bound to exact components/contracts')

def validate_common_v3_bundle(raw,key):
 """Qualified/default authority: candidate-purpose fields/entries are rejected."""
 return _validate_common_v3_bundle(raw,key)

def create_common_v3_bundle(release,output,private_key,public_key):
 output=Path(output).absolute();release=Path(release).resolve()
 if output.exists() or output.is_symlink() or output.resolve().is_relative_to(ROOT/'inputs'):raise ValueError('output must be new and outside inputs')
 if not release.is_file() or release.stat().st_size>65536:raise ValueError('bounded release descriptor required')
 raw=release.read_bytes();d=strict_json(raw);exact(d,BASE|{'loader','qualification'},INPUT_OPTIONAL);common_fields(d)
 handoff=validate_watchdog_handoff(d['watchdogHandoff']) if 'watchdogHandoff' in d else None
 sources={'release':dict(path=str(release),sha256=sha(raw))}
 def source(name,limit=MAX_IMAGE):
  ref=d[name];exact(ref,{'path','sha256'})
  if type(ref['path']) is not str:raise ValueError('source path must be string')
  path=(release.parent/ref['path']).resolve()
  if not path.is_file() or not 1<=path.stat().st_size<=limit:raise ValueError('source bound violated')
  data=path.read_bytes()
  if sha(data)!=digest(ref['sha256']):raise ValueError('source hash mismatch')
  sources[name]=dict(path=str(path),sha256=sha(data));return data
 key=load_public_key(public_key)
 private=serialization.load_pem_private_key(Path(private_key).read_bytes(),password=None)
 if not isinstance(private,ec.EllipticCurvePrivateKey) or not isinstance(private.curve,ec.SECP256R1) or private.public_key().public_numbers()!=key.public_numbers():raise ValueError('matching ECDSA P256 keys required')
 blobs={name:source(name) for name in ROLES if name in d};metadata={name:verify_image(blob,key,name) for name,blob in blobs.items()}
 loader=source('loader',LOADER_SIZE);loader_descriptor(loader,d['loaderContracts'])
 if metadata['recovery']['signedRegionSha256']!=d['targetRecoverySignedHash']:raise ValueError('target REC signed-region mismatch')
 carrier=source('zigbeeOta') if 'zigbeeOta' in d else None
 ota=verify_zigbee_carrier(carrier,blobs['main'],key,metadata['main']) if carrier is not None else None
 qraw=source('qualification',65536);q=strict_json(qraw)
 qualified={**{n:sha(b) for n,b in blobs.items()},'loader':sha(loader)}
 if carrier is not None:qualified['zigbeeOta']=sha(carrier)
 if type(q) is not dict or any(type(q.get(k)) is not int or q[k]!=v for k,v in [('schemaVersion',3),('layoutVersion',2)]) or q.get('model')!='VIMAR30805' or any(q.get(k) is not True for k in (*REQUIRED_CHECKS,*SPLIT_REQUIRED_CHECKS,'commonFirstFlashVerified')) or ('stockRestore' in d and q.get('stockRestoreVerified') is not True) or q.get('loaderContracts')!=d['loaderContracts'] or q.get('components')!=qualified:raise ValueError('incomplete or mismatched hardware qualification')
 first=canonical(first_descriptor(loader,metadata,d['loaderContracts'],handoff));firstsig=private.sign(first,ec.ECDSA(hashes.SHA256()))
 manifest={k:v for k,v in d.items() if k not in {'loader','qualification',*ROLES,'zigbeeOta','watchdogHandoff'}}
 manifest.update(metadata);manifest['qualificationSha256']=sha(qraw)
 if ota is not None:manifest['zigbeeOta']=ota
 manifest['firstInstall']=dict(file='first-install.json',size=len(first),sha256=sha(first),signatureFile='first-install.sig',signatureSha256=sha(firstsig))
 manifest['bundleId']=sha(canonical(manifest));mraw=canonical(manifest);signature=private.sign(mraw,ec.ECDSA(hashes.SHA256()))
 entries={'manifest.json':mraw,'manifest.sig':signature,'loader.bin':loader,'first-install.json':first,'first-install.sig':firstsig,**{FILES[n]:b for n,b in blobs.items()}}
 if carrier is not None:entries['main.ota']=carrier
 stream=io.BytesIO()
 with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_STORED) as archive:
  for name,data in entries.items():
   info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.external_attr=0o100644<<16;archive.writestr(info,data)
 result=stream.getvalue();validate_common_v3_bundle(result,key)
 output.parent.mkdir(parents=True,exist_ok=True)
 with output.open('xb') as destination:destination.write(result)
 return dict(path=str(output),sha256=sha(result),bundleId=manifest['bundleId'],sources=sources,hardware_qualification_required=True,transformations=['verbatim ordinary signed role/profile components; exact typed loader family and FF placeholder template; canonical signed first-install descriptor inside canonical signed common schema3 ZIP'])

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 for name in ('release','output','private-key','public-key'):parser.add_argument('--'+name,type=Path,required=True)
 print(json.dumps(create_common_v3_bundle(**vars(parser.parse_args())),indent=2))
if __name__=='__main__':main()
