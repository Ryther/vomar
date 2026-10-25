#!/usr/bin/env python3
"""Explicit signed ONE-ZIP single-bench candidate; never a qualified release.

All normal release crypto/roles/family/bindings remain mandatory. The signed
purpose is qualification-candidate, with exact hash-bound literal-false physical
report. Default release validators reject this extra purpose/entry. No hardware,
network publication, fleet approval or private original backup is involved.
"""
import argparse,io,json,subprocess,sys,tempfile,zipfile
from dataclasses import dataclass
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tools.firmware.package_common_android_update_v3 import (BASE,INPUT_OPTIONAL,ROLES,FILES,MAX_IMAGE,strict_json,exact,common_fields,load_public_key,verify_image,loader_descriptor,first_descriptor,validate_watchdog_handoff,validate_pending_qualification,_validate_common_v3_bundle,canonical,sha,digest,verify_signature,verify_zigbee_carrier)
PURPOSE='qualification-candidate'

@dataclass(frozen=True)
class ValidatedCandidateBundle:
 """Distinct immutable authority; properties return fresh views, never approval."""
 raw:bytes
 manifest_bytes:bytes
 qualification_bytes:bytes
 purpose:str=PURPOSE
 @property
 def manifest(self):return strict_json(self.manifest_bytes)
 @property
 def qualification(self):return strict_json(self.qualification_bytes)

def validate_candidate_bundle(raw,public_key):
 _validate_common_v3_bundle(raw,public_key,expected_purpose=PURPOSE)
 with zipfile.ZipFile(io.BytesIO(raw)) as archive:return ValidatedCandidateBundle(raw,archive.read('manifest.json'),archive.read('qualification.json'))

def prepare_candidate_bundle(release,output,private_key,public_key):
 output=Path(output).absolute();release=Path(release).resolve()
 if output.exists() or output.is_symlink() or output.resolve().is_relative_to(ROOT/'inputs'):raise ValueError('output must be new and outside immutable inputs')
 if not release.is_file() or release.stat().st_size>65536:raise ValueError('bounded candidate input required')
 d=strict_json(release.read_bytes());exact(d,BASE|{'loader','qualification'},INPUT_OPTIONAL);common_fields(d)
 handoff=validate_watchdog_handoff(d['watchdogHandoff']) if 'watchdogHandoff' in d else None
 key=load_public_key(public_key);sources={};commands=[]
 def source(name,limit=MAX_IMAGE):
  ref=d[name];exact(ref,{'path','sha256'})
  if type(ref['path']) is not str:raise ValueError('exact source path required')
  path=(release.parent/ref['path']).resolve()
  if not path.is_file() or not 1<=path.stat().st_size<=limit:raise ValueError('source bound violated')
  data=path.read_bytes()
  if sha(data)!=digest(ref['sha256']):raise ValueError('source hash mismatch')
  sources[name]=dict(path=str(path),sha256=sha(data));return data
 blobs={name:source(name) for name in ROLES if name in d};metadata={name:verify_image(blob,key,name) for name,blob in blobs.items()}
 loader=source('loader',0xc000);loader_descriptor(loader,d['loaderContracts'])
 carrier=source('zigbeeOta') if 'zigbeeOta' in d else None
 ota=verify_zigbee_carrier(carrier,blobs['main'],key,metadata['main']) if carrier is not None else None
 qraw=source('qualification',65536);validate_pending_qualification(strict_json(qraw),d,blobs,loader,carrier)
 if metadata['recovery']['signedRegionSha256']!=d['targetRecoverySignedHash']:raise ValueError('target REC signed-region mismatch')
 def sign(data,label,folder):
  payload=folder/(label+'.json');signature=folder/(label+'.sig');payload.write_bytes(data)
  command=['openssl','dgst','-sha256','-sign',str(Path(private_key).resolve()),'-out',str(signature),str(payload)];commands.append(command)
  result=subprocess.run(command,capture_output=True,text=True,timeout=120)
  if result.returncode:raise ValueError('candidate signing failed')
  sig=signature.read_bytes();verify_signature(key,sig,data);return sig
 with tempfile.TemporaryDirectory(prefix='vimar-candidate-public-payload-') as td:
  folder=Path(td);first=canonical(first_descriptor(loader,metadata,d['loaderContracts'],handoff));firstsig=sign(first,'first-install',folder)
  manifest={k:v for k,v in d.items() if k not in {'loader','qualification',*ROLES,'zigbeeOta','watchdogHandoff'}}
  manifest.update(metadata);manifest.update(purpose=PURPOSE,qualificationSha256=sha(qraw),firstInstall=dict(file='first-install.json',size=len(first),sha256=sha(first),signatureFile='first-install.sig',signatureSha256=sha(firstsig)))
  if ota is not None:manifest['zigbeeOta']=ota
  manifest['bundleId']=sha(canonical(manifest));mraw=canonical(manifest);msig=sign(mraw,'manifest',folder)
 entries={'manifest.json':mraw,'manifest.sig':msig,'qualification.json':qraw,'loader.bin':loader,'first-install.json':first,'first-install.sig':firstsig,**{FILES[n]:b for n,b in blobs.items()}}
 if carrier is not None:entries['main.ota']=carrier
 stream=io.BytesIO()
 with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_STORED) as archive:
  for name,data in entries.items():
   info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.external_attr=0o100644<<16;archive.writestr(info,data)
 raw=stream.getvalue();validate_candidate_bundle(raw,key)
 output.parent.mkdir(parents=True,exist_ok=True)
 with output.open('xb') as destination:destination.write(raw)
 return dict(path=str(output),sha256=sha(raw),bundleId=manifest['bundleId'],purpose=PURPOSE,hardware_qualified=False,qualified_release=False,sources=sources,commands=commands,qualificationSha256=sha(qraw),entries={n:sha(b) for n,b in entries.items()})

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for field in ('release','output','private-key','public-key'):p.add_argument('--'+field,type=Path,required=True)
 print(json.dumps(prepare_candidate_bundle(**vars(p.parse_args())),indent=2))
if __name__=='__main__':main()
