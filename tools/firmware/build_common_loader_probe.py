#!/usr/bin/env python3
"""Build an isolated UNSIGNED common-loader admission probe; never access hardware.

Only the configured public key is read. No anchor is generated/programmed, no
firmware is signed, and no release compatibility/qualification is asserted.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tools.firmware.toolchain_paths import toolchain_paths
from tools.firmware.validate_recovery import read_config,read_hex,read_partitions,PARTITIONS,validate_uicr_preservation

def sha(data):return hashlib.sha256(data).hexdigest()
def build_probe(output, watchdog_handoff=False):
 if not isinstance(watchdog_handoff,bool):raise ValueError('watchdog_handoff must be an explicit boolean')
 paths=toolchain_paths();output=Path(output).resolve()
 public=paths['public_key'].read_bytes()
 if b'-----BEGIN PUBLIC KEY-----' not in public or b'PRIVATE KEY' in public:
  raise ValueError('probe accepts an existing public-only verification key')
 if output.is_relative_to(ROOT/'inputs') or (output.exists() and any(output.iterdir())):
  raise ValueError('probe output must be new/empty and outside immutable inputs')
 output.mkdir(parents=True,exist_ok=True)
 source=output/'source/firmware'
 shutil.copytree(ROOT/'firmware',source,ignore=shutil.ignore_patterns('keys','__pycache__'))
 report=dict(schema_version=1,kind='unsigned-common-loader-admission-probe',hardware_qualified=False,
  deployable=False,status='build started',public_key_sha256=sha(public),
  source_sha256={str(p.relative_to(output/'source')):sha(p.read_bytes()) for p in source.rglob('*') if p.is_file()},
  builder_sha256=sha(Path(__file__).read_bytes()),commands=[])
 config=output/'probe.conf'
 config.write_text('CONFIG_BOOT_FIRMWARE_LOADER=y\nCONFIG_BOOT_VALIDATE_SLOT0=y\n'
  'CONFIG_BOOT_SIGNATURE_TYPE_ECDSA_P256=y\nCONFIG_BOOT_ECDSA_CC310=y\n'
  'CONFIG_BOOT_FIH_PROFILE_OFF=y\nCONFIG_FPROTECT=y\nCONFIG_BOOT_FIRMWARE_LOADER_DETECT_DELAY=500\n'
  'CONFIG_PM_PARTITION_SIZE_MCUBOOT=0xc000\nCONFIG_VIMAR_COMMON_RESTORE_GATE=y\n'
  'CONFIG_BOOT_SIGNATURE_KEY_FILE="'+str(paths['public_key'])+'"\n')
 build=output/'build'
 command=[str(paths['west']),'build','--pristine','--no-sysbuild','-b','nrf52840dk/nrf52840',
  str(paths['sdk']/'bootloader/mcuboot/boot/zephyr'),'-d',str(build),'--target','zephyr/zephyr.elf','--',
  '-DCONF_FILE='+';'.join(map(str,[paths['sdk']/'bootloader/mcuboot/boot/zephyr/prj.conf',source/'sysbuild/mcuboot_ota.conf'])),
  '-DEXTRA_CONF_FILE='+';'.join(map(str,[source/'research/loader-software-recovery.conf',source/'research/vimar-candidate.conf',config])),
  '-DDTC_OVERLAY_FILE='+';'.join(map(str,[source/'boards/ota-mcuboot.overlay',source/'research/vimar-candidate.overlay'])),
  '-DZEPHYR_EXTRA_MODULES='+str(source/'common_restore_gate')]
 if watchdog_handoff:
  with config.open('a') as extra:extra.write('CONFIG_VIMAR_INHERITED_WATCHDOG_HANDOFF=y\n')
 report['commands'].append(command)
 rp=output/'probe-manifest.json';rp.write_text(json.dumps(report,indent=2)+'\n')
 with (output/'build.log').open('w') as log:
  subprocess.run(command,cwd=paths['sdk'],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=900)
 values=read_config(build/'zephyr/.config')
 required=['CONFIG_MCUBOOT','CONFIG_SOC_NRF52840','CONFIG_BOOT_FIRMWARE_LOADER','CONFIG_BOOT_VALIDATE_SLOT0',
  'CONFIG_BOOT_SIGNATURE_TYPE_ECDSA_P256','CONFIG_BOOT_USE_CC310','CONFIG_BOOT_USE_NRF_CC310_BL',
  'CONFIG_BOOT_FIH_PROFILE_OFF','CONFIG_FPROTECT','CONFIG_MCUBOOT_USE_TLV_ALLOW_LIST','CONFIG_VIMAR_COMMON_RESTORE_GATE']
 forbidden=['CONFIG_VIMAR_STOCK_RESTORE_GATE','CONFIG_BOOT_VALIDATE_SLOT0_ONCE','CONFIG_BOOT_BYPASS_KEY_MATCH',
  'CONFIG_NCS_MCUBOOT_LCS_AWARE','CONFIG_MCUBOOT_ACTION_HOOKS','CONFIG_BOOT_IMAGE_ACCESS_HOOKS',
  'CONFIG_BOOT_GO_HOOKS','CONFIG_BOOT_FLASH_AREA_HOOKS',
  'CONFIG_BOOT_ENCRYPT_IMAGE','CONFIG_NORDIC_QSPI_NOR','CONFIG_SOC_DCDC_NRF52X','CONFIG_SOC_DCDC_NRF52X_HV']
 if any(values.get(k)!='y' for k in required) or any(values.get(k)=='y' for k in forbidden):
  raise ValueError('effective native probe configuration violates admission contract')
 if (values.get('CONFIG_VIMAR_INHERITED_WATCHDOG_HANDOFF')=='y')!=watchdog_handoff:
  raise ValueError('effective inherited-watchdog handoff does not match requested mode')
 if values.get('CONFIG_BOOT_SIGNATURE_KEY_FILE')!='"'+str(paths['public_key'])+'"':raise ValueError('public verification key mismatch')
 ninja=(build/'build.ninja').read_text()
 defines=set(re.findall(r'-D([A-Za-z0-9_]+)',ninja));validate_uicr_preservation({'loader':values},{'loader':defines})
 if 'firmware_loader.c.obj' not in ninja or 'src/loader.c.obj' in ninja:raise ValueError('not audited SDK firmware-loader path')
 if read_partitions((build/'zephyr/zephyr.dts').read_text())!=PARTITIONS:raise ValueError('physical partition layout moved')
 mapped=read_hex(build/'zephyr/zephyr.hex')
 if not mapped or min(mapped)!=0 or max(mapped)>=0xb000:raise ValueError('linked code/ROM data overlaps anchor or outside loader')
 map_text=(build/'zephyr/zephyr.map').read_text()
 matches=re.findall(r'0x([0-9a-fA-F]+)\s+_flash_used\s*=',map_text)
 if len(matches)!=1 or int(matches[0],16)>0xb000:raise ValueError('missing/excessive initialized-ROM load extent')
 if 'Common restore gate code/ROM data overlaps reserved anchor page' not in (build/'zephyr/linker.cmd').read_text():
  raise ValueError('native link did not include reservation assertion')
 if any((build/'zephyr').glob('*.signed.*')):raise ValueError('unexpected signed output in unsigned probe')
 artifacts=output/'unsigned';artifacts.mkdir()
 report['artifacts']={}
 for filename in ['zephyr.elf','zephyr.bin','zephyr.hex','zephyr.map','zephyr.dts','.config']:
  src=build/'zephyr'/filename;dst=artifacts/filename;shutil.copyfile(src,dst)
  report['artifacts'][filename]=dict(size=dst.stat().st_size,sha256=sha(dst.read_bytes()))
 from elftools.elf.elffile import ELFFile
 with (build/'zephyr/zephyr.elf').open('rb') as elf_file:
  elf=ELFFile(elf_file);symbols=elf.get_section_by_name('.symtab')
  hooks=symbols.get_symbol_by_name('vimar_inherited_watchdog_boot_gate') or []
  hook_init=None
  if watchdog_handoff:
   if len(hooks)!=1 or not(0<int(hooks[0]['st_size']) and (int(hooks[0]['st_value'])&~1)+int(hooks[0]['st_size'])<=0xb000):
    raise ValueError('missing or out-of-bounds inherited watchdog boot hook')
   def symbol(name):
    matches=symbols.get_symbol_by_name(name) or []
    if len(matches)!=1:raise ValueError('missing unique loader initialization symbol '+name)
    return matches[0]
   entry=symbol('__init_vimar_inherited_watchdog_boot_gate')
   begin=int(symbol('__init_PRE_KERNEL_1_start')['st_value']);end=int(symbol('__init_PRE_KERNEL_2_start')['st_value'])
   at=int(entry['st_value']);size=int(entry['st_size'])
   if not(begin<=at<at+size<=end<=0xb000 and size==8):
    raise ValueError('watchdog hook is not registered inside early PRE_KERNEL_1')
   section=elf.get_section(entry['st_shndx']);offset=at-int(section['sh_addr'])
   initialized=section.data()[offset:offset+8]
   if int.from_bytes(initialized[:4],'little')!=int(hooks[0]['st_value']) or initialized[4:]!=bytes(4):
    raise ValueError('watchdog early initialization does not point to the actual hook')
   placed=list(re.finditer(r'\.z_init_PRE_KERNEL_1_P_(\d+)_SUB_[^\n]*\n\s+0x([0-9a-fA-F]+)\s+0x([0-9a-fA-F]+)\s+[^\n]*\(inherited_watchdog_boot\.c\.obj\)',map_text))
   if len(placed)!=1 or placed[0][1]!='0' or int(placed[0][2],16)!=at or int(placed[0][3],16)!=size:
    raise ValueError('watchdog initialization map does not prove priority zero')
   hook_init=dict(entry=at,size=size,level='PRE_KERNEL_1',priority=0,
    function_pointer=int(hooks[0]['st_value']),level_start=begin,next_level_start=end)
  elif hooks:raise ValueError('unexpected inherited watchdog hook in inactive-only loader')
 report.update(status='unsigned linked common-loader admission probe; review and consumer integration pending',
  flash_used=int(matches[0],16),code_margin=0xb000-int(matches[0],16),physical_loader_size=0xc000,
  anchor_offset=0xb000,anchor_size=0x1000,unsigned_hex_min=min(mapped),unsigned_hex_max=max(mapped),
  config_sha256=sha((build/'zephyr/.config').read_bytes()),startup_uicr_checks_passed=True,
  family_hash_compiled_into_loader=False,private_key_read=False,firmware_signed=False,
  watchdog_handoff=watchdog_handoff,
  watchdog_handoff_policy='paused-reset-before-main-v1' if watchdog_handoff else None,
  watchdog_handoff_init=hook_init,
  watchdog_handoff_symbol=(dict(address=int(hooks[0]['st_value']),size=int(hooks[0]['st_size'])) if hooks else None))
 rp.write_text(json.dumps(report,indent=2)+'\n')
 return rp

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--watchdog-handoff',action='store_true');a=p.parse_args();print(build_probe(a.output,a.watchdog_handoff))
if __name__=='__main__':main()
