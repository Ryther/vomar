#!/usr/bin/env python3
"""Freeze explicit release loader/recovery bindings; no device/network access.

The loader registry is derived from exact device-bound migration/restoration
artifacts, never from version strings. A pinned reference configuration records
layout-audit provenance; this tool does not claim hardware qualification or prove
binary/config correspondence by itself. Existing release qualification remains
mandatory. Generate recovery header first, then a main header pinning the final
signed recovery and its native configuration (avoids a self-hash cycle).
"""
import argparse,hashlib,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tools.firmware.build_ota_migration import validate_manifest,check_slot
from tools.firmware.package_zigbee_ota import run_imgtool,PUBLIC_KEY
from tools.firmware.validate_recovery import read_config
ROOT=Path(__file__).resolve().parents[2]
def sha(b):return hashlib.sha256(b).hexdigest()
def prepare_pair_bindings(manifest_path,output_dir):
 manifest_path=Path(manifest_path).resolve();output=Path(output_dir).resolve()
 if output.is_relative_to(ROOT/'inputs'):raise ValueError('immutable inputs')
 if output.exists() and any(output.iterdir()):raise ValueError('output must be empty')
 manifest=json.loads(manifest_path.read_text())
 if type(manifest.get('schema_version')) is not int or manifest['schema_version']!=1:raise ValueError('unsupported bindings schema')
 def record(entry):
  if not isinstance(entry,dict) or not isinstance(entry.get('path'),str) or not re.fullmatch('[0-9a-f]{64}',str(entry.get('sha256'))):raise ValueError('invalid source record')
  p=(manifest_path.parent/entry['path']).resolve();data=p.read_bytes()
  if sha(data)!=entry['sha256']:raise ValueError('source SHA256 mismatch')
  return p,data
 config_path,config_data=record(manifest.get('audited_loader_config'));config=read_config(config_path)
 for key in ['CONFIG_BOOT_FIRMWARE_LOADER','CONFIG_BOOT_VALIDATE_SLOT0','CONFIG_BOOT_SIGNATURE_TYPE_ECDSA_P256']:
  if config.get(key)!='y':raise ValueError('unsupported loader config: '+key)
 for key in ['CONFIG_BOOT_SWAP_USING_SCRATCH','CONFIG_BOOT_SWAP_USING_OFFSET','CONFIG_BOOT_SWAP_USING_MOVE','CONFIG_BOOT_ENCRYPT_IMAGE']:
  if config.get(key)=='y':raise ValueError('unsupported loader trailer/swap layout')
 entries=manifest.get('loader_authorizations')
 if not isinstance(entries,list) or not 1<=len(entries)<=64:raise ValueError('missing authorized loaders')
 allowed=[];authorizations=[]
 for entry in entries:
  if not isinstance(entry,dict):raise ValueError('invalid loader authorization')
  source,source_data=record(entry.get('manifest'));legacy_recovery,_=record(entry.get('recovery'))
  checked=validate_manifest(source,legacy_recovery)
  if checked['loader_sha256'] not in allowed:allowed.append(checked['loader_sha256'])
  authorizations.append({'uid':checked['uid'],'loader_sha256':checked['loader_sha256'],'authorization_manifest_sha256':sha(source_data)})
 recovery_hash=None;recovery_end=None;recovery_config_sha256=None;recovery_version=None;commands=[]
 if 'recovery_signed' in manifest or 'recovery_config' in manifest:
  path,data=record(manifest.get('recovery_signed'));cfg,cfg_data=record(manifest.get('recovery_config'))
  recovery_version=manifest.get('recovery_version','0.7.3+0')
  if 'recovery_version' in manifest and (not isinstance(recovery_version,str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',recovery_version)):
   raise ValueError('explicit recovery version must be a SemVer triple')
  parsed=check_slot(data,0xb0000,0x34000,recovery_version)
  if 'recovery_version' in manifest and (parsed['protected'].get(0xa0)!=b'VIMAR30805\x02' or parsed['protected'].get(0xa1)!=b'\x02'):
   raise ValueError('explicit recovery version requires protected RECOVERY role/profile2')
  values=read_config(cfg)
  if any(values.get(k)!='y' for k in ['CONFIG_VIMAR_OTA_SPLIT_STAGING','CONFIG_VIMAR_P031_PROTECTION','CONFIG_VIMAR_OTA_INSTALLER']):raise ValueError('recovery does not enable protected split profile')
  if values.get('CONFIG_NRF_COMPRESS_LZMA_MAX_DICT_SIZE')!='32768':raise ValueError('unsupported dictionary')
  if values.get('CONFIG_DISABLE_FLASH_PATCH')=='y':raise ValueError('UICR writer forbidden')
  run_imgtool(['verify','-k',PUBLIC_KEY,path],commands)
  recovery_hash=sha(data);recovery_end=0xb0000+len(data);recovery_config_sha256=sha(cfg_data)
 rows=[','.join('0x'+x[i:i+2] for i in range(0,64,2)) for x in allowed]
 header='#ifndef VIMAR_OTA_PAIR_BINDINGS_H\n#define VIMAR_OTA_PAIR_BINDINGS_H\n#include <stdint.h>\n#include <stddef.h>\n'
 header+='static const uint8_t ota_allowed_loaders[][32] = {\n'+''.join('{'+row+'},\n' for row in rows)+'};\n'
 header+=f'static const size_t ota_allowed_loader_count={len(allowed)};\n'
 digest=recovery_hash or '00'*32
 header+='static const uint8_t ota_expected_recovery_digest[32] __attribute__((unused)) = {'+','.join('0x'+digest[i:i+2] for i in range(0,64,2))+'};\n#endif\n'
 output.mkdir(parents=True,exist_ok=True);hp=output/'pair_bindings.h';hp.write_text(header)
 report={'schema_version':1,'ota_profile':2,'allowed_loaders':allowed,'recovery_sha256':recovery_hash,'recovery_end':recovery_end,
 'reference_loader_config_sha256':sha(config_data),'loader_config_provenance_requires_qualification':True,'authorizations':authorizations,
 'recovery_config_sha256':recovery_config_sha256,'recovery_version':recovery_version,'header_sha256':sha(hp.read_bytes()),'hardware_qualified':False,
 'source_manifest_sha256':sha(manifest_path.read_bytes()),'commands':commands}
 rp=output/'pair_bindings.json';rp.write_text(json.dumps(report,indent=2)+'\n')
 return {'header_path':str(hp),'report_path':str(rp)}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(prepare_pair_bindings(a.manifest,a.output),indent=2))
if __name__=='__main__':main()
