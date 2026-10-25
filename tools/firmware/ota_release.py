"""Qualification gate for initial installation of an OTA-capable signed pair.

This module has no hardware access. A private schema1 pair manifest pins ordinary
signed main/recovery BIN files and a JSON qualification report by exact SHA256.
All REQUIRED_CHECKS must be literal true in that report. A transfer response alone
cannot authorize fleet provisioning; physical power-cut qualification is required.
"""
import hashlib,json,re,tempfile
from pathlib import Path
from tools.firmware.build_ota_migration import check_slot
from tools.firmware.package_zigbee_ota import run_imgtool,PUBLIC_KEY,version_tuple
REQUIRED_CHECKS=('zigbee_ota_completed','postboot_hash_verified','ble_recovery_verified','power_cut_recovery_verified')
SPLIT_REQUIRED_CHECKS=('split_stage_verified','loader_binding_verified','recovery_tail_preserved','mixed_profile_rejected','protection_flash_radio_verified','stock_restore_verified','migration_verified')

def load_ota_pair(path):
 path=Path(path).resolve();raw=path.read_bytes();manifest=json.loads(raw)
 if type(manifest.get('schema_version')) is not int or manifest['schema_version']!=1:
  raise ValueError('Unsupported OTA pair schema')
 def read_record(name):
  entry=manifest.get(name)
  if not isinstance(entry,dict) or not isinstance(entry.get('path'),str) or not re.fullmatch('[0-9a-f]{64}',str(entry.get('sha256'))):
   raise ValueError('Invalid OTA pair source: '+name)
  source=(path.parent/entry['path']).resolve();data=source.read_bytes()
  if hashlib.sha256(data).hexdigest()!=entry['sha256']:raise ValueError('SHA256 mismatch: '+name)
  return {'path':str(source),'data':data,'sha256':entry['sha256']}
 profile=manifest.get('ota_profile',1)
 if type(profile) is not int or profile not in (1,2):raise ValueError('Unsupported OTA profile')
 evidence=read_record('qualification');checks=json.loads(evidence['data'])
 if not isinstance(checks,dict) or type(checks.get('schema_version')) is not int or checks['schema_version']!=1 or any(checks.get(k) is not True for k in REQUIRED_CHECKS):
  raise ValueError('Incomplete hardware qualification for OTA pair')
 if profile==2:
  if checks.get('ota_profile')!=2 or any(checks.get(k) is not True for k in SPLIT_REQUIRED_CHECKS):
   raise ValueError('Incomplete split OTA qualification')
  binding=read_record('pair_bindings');bound=json.loads(binding['data'])
  if bound.get('ota_profile')!=2 or bound.get('recovery_sha256')!=manifest.get('recovery',{}).get('sha256') or not bound.get('allowed_loaders') or bound.get('allowed_loaders')!=checks.get('allowed_loaders'):
   raise ValueError('Unbound split OTA qualification')
 result={'manifest_path':str(path),'manifest_sha256':hashlib.sha256(raw).hexdigest(),'qualification':{'path':evidence['path'],'sha256':evidence['sha256']},'qualification_data':evidence['data']}
 commands=[]
 with tempfile.TemporaryDirectory(prefix='vimar-qualified-pair-') as temp:
  for name,base,capacity in [('main',0xc000,0xa4000),('recovery',0xb0000,0x40000)]:
   entry=read_record(name);version=manifest[name].get('version')
   if checks.get(name+'_sha256')!=entry['sha256']:raise ValueError('Image not bound to qualification: '+name)
   if not isinstance(version,str):raise ValueError('Missing signed image version: '+name)
   parsed=check_slot(entry['data'],base,0x34000 if profile==2 and name=='recovery' else capacity,version)
   numbers=version_tuple(version)
   if numbers<(((0,5,7,1) if name=='main' else (0,7,3,0)) if profile==2 else ((0,5,2,0) if name=='main' else (0,7,1,0))):
    raise ValueError('Legacy image version lacks qualified OTA pair support')
   frozen=Path(temp)/(name+'.bin');frozen.write_bytes(entry['data'])
   run_imgtool(['verify','-k',PUBLIC_KEY,frozen],commands)
   entry['version']=parsed['version'];result[name]=entry
 if profile==2:result['ota_profile']=2;result['pair_bindings']={'path':binding['path'],'sha256':binding['sha256']};result['pair_bindings_data']=binding['data']
 return result
