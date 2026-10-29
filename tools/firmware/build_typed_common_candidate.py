#!/usr/bin/env python3
"""Build a matched LOCAL typed candidate set, never hardware or a qualified ZIP.

Explicit existing project-key signing is performed only by imgtool/openssl.
Firmware snapshots exclude keys. Qualification remains false; staged ONE-ZIP
entries are incomplete without the separately gated qualified outer signature.
"""
import argparse,ctypes,hashlib,json,os,re,shutil,struct,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from cryptography.hazmat.primitives import serialization
from tools.firmware.toolchain_paths import toolchain_paths
from tools.firmware import build_common_loader_probe as loader_builder
from tools.firmware.build_common_restore_probe import inspect_elf
from tools.firmware.build_loader_contract_bindings import generate
from tools.firmware.loader_runtime_contract import measure_record,COMMON_KIND,LEGACY_KIND,validate_records
from tools.firmware.package_common_android_update_v3 import verify_image,first_descriptor,canonical,verify_signature,validate_watchdog_handoff,WATCHDOG_HANDOFF
from tools.firmware.package_common_android_update import verify_zigbee_carrier
from tools.firmware.package_zigbee_ota import split_stage_budget,image,ENCODER_ADAPTER
from tools.firmware.ota_release import REQUIRED_CHECKS,SPLIT_REQUIRED_CHECKS
from tools.firmware.validate_recovery import read_config,read_hex,validate_uicr_preservation
VERSIONS=dict(main='0.6.1',recovery='0.8.1',migration='0.9.1',stockRestore='0.10.0',stockBootstrap='0.11.0')
WATCHDOG_VERSIONS=dict(main='0.6.2',recovery='0.8.2',migration='0.9.2',stockRestore='0.10.1',stockBootstrap='0.11.1')
MULTIBOND_VERSIONS=dict(main='0.6.3',recovery='0.8.3',migration='0.9.3',stockRestore='0.10.2',stockBootstrap='0.11.2')
ROLES=dict(main=1,recovery=2,migration=3,stockRestore=4,stockBootstrap=3)

def sha(data):return hashlib.sha256(data).hexdigest()
def write_json(path,value):Path(path).write_text(json.dumps(value,indent=2)+'\n');return Path(path)
def version(path,value):
 a,b,c=value.split('.');Path(path).write_text(f'VERSION_MAJOR = {a}\nVERSION_MINOR = {b}\nPATCHLEVEL = {c}\nVERSION_TWEAK = 0\nEXTRAVERSION =\n')
def c_bytes(name,data):return 'static const uint8_t '+name+'[] __attribute__((aligned(4))) = {\n'+','.join('0x%02x'%v for v in data)+'\n};\n'
def public_record(path):
 p=Path(path);return dict(path=str(p),sha256=sha(p.read_bytes()),size=p.stat().st_size)
def prepare_output(path):
 p=Path(path).resolve()
 if p.is_relative_to(ROOT/'inputs') or p.exists():raise ValueError('candidate output must be NEW and outside inputs')
 p.mkdir(parents=True);return p

def require_watchdog_loader(probe_manifest):
 """Check linked public artifacts before authorising the descriptor capability."""
 from elftools.elf.elffile import ELFFile
 probe_manifest=Path(probe_manifest);report=json.loads(probe_manifest.read_text());unsigned=probe_manifest.parent/'unsigned'
 for name in ('.config','zephyr.elf'):
  if sha((unsigned/name).read_bytes())!=report['artifacts'][name]['sha256']:raise ValueError('watchdog loader artifact hash mismatch')
 if read_config(unsigned/'.config').get('CONFIG_VIMAR_INHERITED_WATCHDOG_HANDOFF')!='y':raise ValueError('watchdog loader handoff configuration is not enabled')
 symbol='vimar_inherited_watchdog_boot_gate'
 with (unsigned/'zephyr.elf').open('rb') as stream:
  elf=ELFFile(stream);symbols=elf.get_section_by_name('.symtab')
  matches=[] if symbols is None else [s for s in symbols.iter_symbols() if s.name==symbol and s['st_info']['type']=='STT_FUNC' and isinstance(s['st_shndx'],int) and s['st_size']>0]
  if elf['e_machine']!='EM_ARM' or len(matches)!=1:raise ValueError('watchdog loader requires linked ARM boot-gate function')
  address=matches[0]['st_value']&~1;size=matches[0]['st_size']
  if not 8<=address<address+size<=0xb000:raise ValueError('watchdog loader function outside loader code area')
 return dict(policy=WATCHDOG_HANDOFF,symbol=symbol,address=address,size=size,config_enabled=True,config_sha256=sha((unsigned/'.config').read_bytes()),elf_sha256=sha((unsigned/'zephyr.elf').read_bytes()))

def candidate_versions(watchdog_handoff=None,multi_bond=False,release_version=None):
 if release_version is not None:
  if not isinstance(release_version,str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)',release_version) or any(int(v)>255 for v in release_version.split('.')):
   raise ValueError('release version must be ordinary SemVer with each OTA field in0..255')
  if watchdog_handoff!=WATCHDOG_HANDOFF or not multi_bond:
   raise ValueError('release profile requires watchdog handoff and multi-bond recovery')
  return {name:release_version for name in ROLES}
 if multi_bond:
  if watchdog_handoff!=WATCHDOG_HANDOFF:raise ValueError('multi-bond candidates require the inherited watchdog handoff policy')
  return dict(MULTIBOND_VERSIONS)
 return dict(WATCHDOG_VERSIONS if watchdog_handoff is not None else VERSIONS)

def fault_build_identity(source_hashes,versions,inputs):
 """Identify archived source/config/pair inputs, outside the linked image cycle."""
 material=dict(domain='vimar-common-fault-v1',sources=source_hashes,versions=versions,
               inputs={name:sha(data) for name,data in inputs.items()})
 return hashlib.sha256(canonical(material)).digest()[:16]

def require_release_main(build,out,cfg):
 """Check actual linked fatal hooks and RAM bound, not a configuration claim."""
 from elftools.elf.elffile import ELFFile
 required=('CONFIG_VIMAR_FAULT_DIAGNOSTICS','CONFIG_ZBOSS_RESET_ON_ASSERT','CONFIG_VIMAR_P031_PROTECTION')
 if any(cfg.get(k)!='y' for k in required):raise ValueError('release MAIN diagnostic/protection configuration missing')
 elf=build/'zephyr/zephyr.elf'
 with elf.open('rb') as stream:
  linked=ELFFile(stream);symbols=linked.get_section_by_name('.symtab')
  names={s.name for s in symbols.iter_symbols() if isinstance(s['st_shndx'],int)} if symbols else set()
  ram=[dict(start=s['p_vaddr'],end=s['p_vaddr']+s['p_memsz']) for s in linked.iter_segments() if s['p_type']=='PT_LOAD' and s['p_memsz'] and 0x20000000<=s['p_vaddr']<0x20040000]
 if not ram or any(s['end']>0x2003fe00 for s in ram):raise ValueError('release MAIN overlaps retained fault record window')
 hooks={'__wrap_zb_osif_abort','vimar_diag_abort_entry','vimar_fault_diag_boot','vimar_fault_diag_error','fault_diag_capture_assert','fault_diag_capture_abort'}
 if not hooks<=names or 'zb_osif_abort' in names:raise ValueError('release MAIN fatal-hook linkage missing or bypassed')
 cache=(build/'CMakeCache.txt').read_text();objdump=Path(re.search(r'^CMAKE_OBJDUMP:FILEPATH=(.+)$',cache,re.M)[1])
 assembly=subprocess.check_output([str(objdump),'-d',str(elf)],text=True)
 calls=[line.strip() for line in assembly.splitlines() if re.search(r'\b(?:bl|b\.w)\b.*<__wrap_zb_osif_abort>',line)]
 wrapper=subprocess.check_output([str(objdump),'-d',str(elf),'--disassemble=__wrap_zb_osif_abort'],text=True)
 (out/'main-abort-guard-disassembly.txt').write_text(wrapper)
 if len(calls)<3 or '<vimar_diag_abort_entry>' not in wrapper or 'mrs' not in wrapper or re.search(r'\b(?:push|str)(?:\.w)?\b',wrapper):raise ValueError('release MAIN abort entry loses original context')
 boundaries={}
 for label,target in [('sdk','modules/ncs-zigbee/subsys/CMakeFiles/..__ncs-zigbee__subsys.dir/osif/zb_nrf_platform.c.obj'),('guard','CMakeFiles/app.dir/src/zigbee_reset_guard.c.obj')]:
  commands=subprocess.check_output(['ninja','-C',str(build),'-t','commands',target],text=True)
  command=next(line for line in commands.splitlines() if ' -o '+target+' ' in line)
  flags=re.findall(r'-flto[^ ]*|-fno-lto',command)
  if not flags or flags[-1]!='-fno-lto':raise ValueError('release MAIN abort boundary may be inlined before wrapping')
  boundaries[label]=flags
 return dict(required_symbols=sorted(hooks),wrapped_calls=calls,ram_segments=ram,
             retained_window=dict(start=0x2003fe00,end=0x2003ff00),lto_boundaries=boundaries)

def write_recovery_config(firmware,destination):
 """Materialize the typed recovery profile from the public source snapshot."""
 typed='CONFIG_VIMAR_LOADER_RUNTIME_V2=y\nCONFIG_MAIN_STACK_SIZE=12288\nCONFIG_MCUBOOT_SIGNATURE_KEY_FILE=""\nCONFIG_MCUBOOT_GENERATE_UNSIGNED_IMAGE=n\n'
 Path(destination).write_text((Path(firmware)/'recovery/migration-exec.conf').read_text()+typed+'CONFIG_MCUMGR_TRANSPORT_WORKQUEUE_STACK_SIZE=8192\n')

def validate_recovery_contract(config):
 """Profile2 is a stable update ABI, independent of recovery SemVer/hash.

 Breaking the journal, layout or codec requires another authenticated profile
 and an explicit migration. Never sign a different ABI as RECOVERY2/profile2.
 """
 required=('CONFIG_VIMAR_OTA_INSTALLER','CONFIG_VIMAR_OTA_SPLIT_STAGING',
  'CONFIG_VIMAR_P031_PROTECTION','CONFIG_NRF_COMPRESS_DECOMPRESSION',
  'CONFIG_NRF_COMPRESS_LZMA_VERSION_LZMA2','CONFIG_NRF_COMPRESS_ARM_THUMB')
 fixed={'CONFIG_NRF_COMPRESS_LZMA_MAX_DICT_SIZE':'32768',
  'CONFIG_NRF_COMPRESS_LZMA_MAX_LC_LP':'3','CONFIG_NRF_COMPRESS_LZMA_LP':'0'}
 if (any(config.get(k)!='y' for k in required) or
     any(config.get(k)!=v for k,v in fixed.items()) or
     config.get('CONFIG_DISABLE_FLASH_PATCH')=='y'):
  raise ValueError('incompatible profile2 recovery contract configuration')
 return 'vimar30805-split-v2'

def build(output,legacy_registry,source_policy,watchdog_handoff=None,multi_bond=False,release_version=None):
 if watchdog_handoff is not None:validate_watchdog_handoff(watchdog_handoff)
 versions=candidate_versions(watchdog_handoff,multi_bond,release_version)
 paths=toolchain_paths();out=prepare_output(output);art=out/'artifacts';art.mkdir();staging=out/'one-zip-staging';staging.mkdir();gen=out/'generated';gen.mkdir();configs=out/'configs';configs.mkdir()
 report=dict(schema_version=1,kind='unqualified-typed-common-candidate',model='VIMAR30805',hardware_qualified=False,deployable=False,qualified_release_zip=False,versions=versions,watchdog_handoff=watchdog_handoff,status='snapshot',commands=[],artifacts={},source_inputs=dict(legacy_registry=public_record(legacy_registry),source_policy=public_record(source_policy)),pending_checks=['independent matched-binary review','owner-controlled first-install and original backup/export/reopen','normal MAIN and recovery BLE identity/history/execution','legacy recovery migration and exact typed loader compatibility','stock bootstrap and full original FLASH/UICR restoration','P031 flash/radio/finalizer timing and physical power-cut recovery','fresh aggregate OTA compatibility and real Zigbee update/return'])
 manifest=out/'candidate-manifest.json'
 def save():write_json(manifest,report)
 def run(argv,logname,cwd=None):
  argv=list(map(str,argv));report['status']='running '+logname;report['commands'].append(dict(argv=argv,cwd=str(cwd or ROOT),log=logname));save();print('start',logname,flush=True)
  env=os.environ.copy();env['PATH']=str(paths['west'].parent)+':'+env['PATH'];env['CMAKE_BUILD_PARALLEL_LEVEL']='2'
  with (out/logname).open('w') as log:subprocess.run(argv,cwd=cwd or ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=1200)
  print('pass',logname,flush=True)
 fw=out/'source/firmware';shutil.copytree(ROOT/'firmware',fw,ignore=shutil.ignore_patterns('keys','__pycache__','build'))
 for name,path in [('main',fw/'VERSION'),('recovery',fw/'recovery/VERSION'),('migration',fw/'ota_migration/VERSION'),('stockRestore',fw/'common_restore/VERSION')]:version(path,versions[name])
 report['workspace_source_sha256']={str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in (ROOT/'firmware').rglob('*') if p.is_file() and 'keys' not in p.relative_to(ROOT/'firmware').parts}
 report['snapshot_source_sha256']={str(p.relative_to(out/'source')):sha(p.read_bytes()) for p in fw.rglob('*') if p.is_file()};report['source_transformations']=['firmware copy excluding all keys/build caches; explicit ordinary candidate VERSION triples only'];save()
 # Existing loader probe reads the PUBLIC verification key only. No self-family hash.
 previous=loader_builder.ROOT
 try:loader_builder.ROOT=out/'source';loader_manifest=loader_builder.build_probe(out/'loader',watchdog_handoff=watchdog_handoff is not None)
 finally:loader_builder.ROOT=previous
 if watchdog_handoff is not None:report['watchdog_handoff_proof']=require_watchdog_loader(loader_manifest);save()
 loader=bytearray(b'\xff'*0xc000);mapped=read_hex(out/'loader/build/zephyr/zephyr.hex')
 if not mapped or min(mapped)!=0 or max(mapped)>=0xb000:raise ValueError('loader ROM overlaps reserved anchor')
 for address,value in mapped.items():loader[address]=value
 loader=bytes(loader);assert loader[0xb000:]==b'\xff'*4096
 (staging/'loader.bin').write_bytes(loader);(art/'loader.bin').write_bytes(loader)
 family=measure_record(loader,COMMON_KIND);old=json.loads(Path(legacy_registry).read_text());legacy=old['allowed_loaders']
 if len(legacy)!=3 or legacy!=sorted(set(legacy)) or any(not re.fullmatch('[0-9a-f]{64}',v) for v in legacy):raise ValueError('exact three known public legacy records required')
 records=sorted([family.as_dict()]+[dict(kind=LEGACY_KIND,sha256=v) for v in legacy],key=lambda r:(r['kind'],r['sha256']));validate_records(records)
 all_header=gen/'loader-contracts.h';all_header.write_bytes(generate(records));common_header=gen/'common-loader-contracts.h';common_header.write_bytes(generate([family.as_dict()]));write_json(gen/'loader-contracts.json',records)
 report['loader_contracts']=records;report['loader']=dict(public_record(art/'loader.bin'),family=family.as_dict(),code_limit=0xb000,anchor_placeholder='FF4096',probe_manifest=public_record(loader_manifest));save()
 target=gen/'target-profile2.bin';target.write_bytes(b'VIMAR30805\x02');public=serialization.load_pem_public_key(paths['public_key'].read_bytes())
 metadata={};signed={};raw={}
 def sign(name,unsigned,base,limit):
  role=gen/('role-'+name+'.bin');role.write_bytes(bytes([ROLES[name]]));dest=art/(name+'-'+versions[name]+'.signed.bin')
  run([paths['python'],paths['imgtool'],'sign','--header-size','512','--slot-size',hex(limit),'--align','4','--overwrite-only','--version',versions[name],'-k',paths['private_key'],'--custom-tlv-file','0xa0',target,'--custom-tlv-file','0xa1',role,unsigned,dest],name+'-sign.log')
  run([paths['python'],paths['imgtool'],'verify','-k',paths['public_key'],dest],name+'-verify.log')
  data=dest.read_bytes();metadata[name]=verify_image(data,public,name);signed[name]=dest;raw[name]=unsigned
  (staging/metadata[name]['file']).write_bytes(data);report['artifacts'][name]=dict(public_record(dest),**metadata[name]);save();return dest
 def native(name,argv,base,limit):
  run(argv,name+'-build.log',paths['sdk']);build=out/(name+'-build');elf=build/'zephyr/zephyr.elf';cfg=read_config(build/'zephyr/.config')
  if cfg.get('CONFIG_MCUBOOT_SIGNATURE_KEY_FILE')!='""':raise ValueError('native stage must not select signing key')
  validate_uicr_preservation({name:cfg},{name:set(re.findall(r'-D([A-Za-z0-9_]+)',(build/'build.ninja').read_text()))})
  from elftools.elf.elffile import ELFFile
  with elf.open('rb') as stream:segments=[dict(start=s['p_paddr'],end=s['p_paddr']+s['p_filesz']) for s in ELFFile(stream).iter_segments() if s['p_type']=='PT_LOAD' and s['p_filesz'] and s['p_paddr']<0x100000]
  if not segments or any(not base<=s['start']<s['end']<=base+limit for s in segments):raise ValueError('ROM/code/initial-data exceeds capacity')
  if any((build/'zephyr').glob('*.signed.*')):raise ValueError('unexpected native signing')
  if name in ('main','recovery','migration'):
   for key in ('CONFIG_VIMAR_LOADER_RUNTIME_V2','CONFIG_VIMAR_P031_PROTECTION','CONFIG_VIMAR_OTA_SPLIT_STAGING'):
    if cfg.get(key)!='y':raise ValueError('missing typed protected config '+key)
   if int(cfg['CONFIG_MAIN_STACK_SIZE'])<12288:raise ValueError('typed stack below bound')
  if name=='main' and (cfg.get('CONFIG_BT')=='y' or cfg.get('CONFIG_VIMAR_ZIGBEE_OTA')!='y'):raise ValueError('normal main radio configuration differs')
  if name=='main' and release_version is not None:
   report['fault_diagnostic_proof']=require_release_main(build,out,cfg)
  if name=='recovery' and (any(cfg.get(k)!='y' for k in ['CONFIG_VIMAR_RECOVERY_IDENTITY','CONFIG_VIMAR_RECOVERY_BOOT_HISTORY','CONFIG_VIMAR_RECOVERY_MIGRATION_EXEC','CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN']) or int(cfg['CONFIG_MCUMGR_TRANSPORT_WORKQUEUE_STACK_SIZE'])<8192):raise ValueError('recovery feature/stack guard failed')
  if name=='recovery':report['recovery_contract']=validate_recovery_contract(cfg)
  if name=='recovery' and multi_bond:
   from tools.firmware.bond_capacity import validate_bond_capacity
   validate_bond_capacity(cfg)
  report.setdefault('native',{})[name]=dict(config_sha256=sha((build/'zephyr/.config').read_bytes()),rom_segments=segments,unsigned_size=(build/'zephyr/zephyr.bin').stat().st_size,capacity=limit)
  for ext in ('bin','elf','hex'):shutil.copy2(build/('zephyr/zephyr.'+ext),art/(name+'.unsigned.'+ext))
  shutil.copy2(build/'zephyr/.config',art/(name+'.config'));save();return art/(name+'.unsigned.bin')
 def make_native(name,source,conf,extras,overlays,extra=()):
  return [paths['west'],'build','--pristine','--no-sysbuild','-b','nrf52840dk/nrf52840',source,'-d',out/(name+'-build'),'--target','zephyr/zephyr.elf','--','-DCONF_FILE='+str(conf),'-DEXTRA_CONF_FILE='+';'.join(map(str,extras)),'-DDTC_OVERLAY_FILE='+';'.join(map(str,overlays)),*extra]
 def maintenance(name,source,blob=None):
  config=configs/(name+'.conf');config.write_text('CONFIG_VIMAR_COMMON_RESTORE_EXPERIMENTAL=y\nCONFIG_DISABLE_FLASH_PATCH=n\nCONFIG_MCUBOOT_SIGNATURE_KEY_FILE=""\nCONFIG_MCUBOOT_GENERATE_UNSIGNED_IMAGE=n\n'+('CONFIG_VIMAR_COMMON_RESTORE_BOOTSTRAP=y\n' if blob else ''))
  extras=[source/'research/vimar-candidate.conf',config];opts=['-DVIMAR_LOADER_CONTRACT_BINDINGS_HEADER='+str(common_header)]
  if blob:
   extras.insert(0,source/'ota/crypto.conf');header=gen/'stock-restorer-blob.h';header.write_text('#include <stdint.h>\n'+c_bytes('common_restore_blob',blob.read_bytes()));opts+=['-DVIMAR_COMMON_RESTORE_BLOB_HEADER='+str(header)]
  argv=make_native(name,source/'common_restore',source/'common_restore/prj.conf',extras,[source/'common_restore'/('bootstrap.overlay' if blob else 'restorer.overlay'),source/'research/vimar-candidate.overlay'],opts)
  body=native(name,argv,0xc000 if blob else 0xb0000,0xa2000 if blob else 0x3f000)
  build=out/(name+'-build');cache=(build/'CMakeCache.txt').read_text();objdump=Path(re.search(r'^CMAKE_OBJDUMP:FILEPATH=(.+)$',cache,re.M)[1]);report['native'][name]['sram_proof']=inspect_elf(build/'zephyr/zephyr.elf',0xc000 if blob else 0xb0000,0xa2000 if blob else 0x3f000,objdump,out/(name+'-disassembly.txt'));save()
  return sign(name,body,0xc000 if blob else 0xb0000,0xa2000 if blob else 0x3f000)
 restorer=maintenance('stockRestore',fw)
 bootstrap_fw=out/'bootstrap-source/firmware';shutil.copytree(fw,bootstrap_fw);version(bootstrap_fw/'common_restore/VERSION',versions['stockBootstrap']);report['bootstrap_source_transformations']=['copy exact candidate source; common_restore/VERSION'+versions['stockBootstrap']+' for distinct primary bootstrap purpose'];report['bootstrap_source_sha256']={str(p.relative_to(out/'bootstrap-source')):sha(p.read_bytes()) for p in bootstrap_fw.rglob('*') if p.is_file()};save()
 bootstrap=maintenance('stockBootstrap',bootstrap_fw,restorer)
 # REC uses only legacy array compatibility fields in the unchanged IO ABI;
 # typed runtime authority is the separate four-record header. No self-REC hash.
 recovery_pair=gen/'recovery-pair.h';recovery_pair.write_text('#include <stdint.h>\n#include <stddef.h>\nstatic const uint8_t ota_allowed_loaders[][32]={'+','.join('{'+','.join('0x'+h[i:i+2] for i in range(0,64,2))+'}' for h in legacy)+'};\nstatic const size_t ota_allowed_loader_count=3;\n')
 typed='CONFIG_VIMAR_LOADER_RUNTIME_V2=y\nCONFIG_MAIN_STACK_SIZE=12288\nCONFIG_MCUBOOT_SIGNATURE_KEY_FILE=""\nCONFIG_MCUBOOT_GENERATE_UNSIGNED_IMAGE=n\n'
 rec_conf=configs/'recovery.conf';write_recovery_config(fw,rec_conf)
 overlays=[fw/'boards/ota-loader.overlay',fw/'research/vimar-candidate.overlay']
 extras=[fw/'research/vimar-candidate.conf',fw/'ota/crypto.conf',fw/'ota/recovery.conf',rec_conf]
 rec_args=make_native('recovery',fw/'recovery',fw/'recovery/prj.conf',extras,overlays,['-DVIMAR_OTA_PAIR_BINDINGS_HEADER='+str(recovery_pair),'-DVIMAR_LOADER_CONTRACT_BINDINGS_HEADER='+str(all_header)])
 recovery=sign('recovery',native('recovery',rec_args,0xb0000,0x34000),0xb0000,0x34000)
 # MAIN authenticates the stable signed recovery ABI. The actual live digest
 # belongs to each operation's journal, not this release's compiled inputs.
 main_pair=gen/'main-pair.h';main_pair.write_text(recovery_pair.read_text())
 main_conf=configs/'main.conf';main_conf.write_text(typed)
 main_overlays=[fw/'boards/nrf52840dk_nrf52840_ota.overlay',fw/'research/vimar-candidate.overlay']
 main_options=['-DVIMAR_OTA_PAIR_BINDINGS_HEADER='+str(main_pair),'-DVIMAR_LOADER_CONTRACT_BINDINGS_HEADER='+str(all_header)]
 if release_version is not None:
  main_conf.write_text(typed+'CONFIG_VIMAR_FAULT_DIAGNOSTICS=y\n')
  build_id=fault_build_identity(report['snapshot_source_sha256'],versions,
      {'main.conf':main_conf.read_bytes(),'main-pair.h':main_pair.read_bytes(),
       'loader-contracts.h':all_header.read_bytes(),'builder.py':Path(__file__).read_bytes()})
  fault_header=gen/'fault-build-id.h'
  fault_header.write_text('#include <stdint.h>\nstatic const uint8_t vimar_fault_build_id[16]={'+','.join(str(b) for b in build_id)+'};\n')
  main_overlays.append(fw/'boards/fault-diagnostics.overlay')
  main_options.append('-DVIMAR_FAULT_BUILD_ID_HEADER='+str(fault_header))
  report['fault_build_id']=build_id.hex();report['release_version']=release_version;save()
 main_args=make_native('main',fw,fw/'prj_split_ota.conf',[fw/'vimar_zigbee.conf',fw/'research/vimar-candidate.conf',fw/'ota/crypto.conf',main_conf],main_overlays,main_options)
 main=sign('main',native('main',main_args,0xc000,0xa2000),0xc000,0xa2000)
 mig_gen=gen/'migration';mig_gen.mkdir();mig_gen.joinpath('recovery_blob.h').write_text('#include <stdint.h>\n#define RECOVERY_BLOB_SIZE '+str(recovery.stat().st_size)+'u\n'+c_bytes('recovery_blob',recovery.read_bytes()))
 mig_conf=configs/'migration.conf';mig_conf.write_text(typed+'CONFIG_MIGRATION_COMMON=y\nCONFIG_VIMAR_OTA_SPLIT_STAGING=y\nCONFIG_VIMAR_P031_PROTECTION=y\nCONFIG_SETTINGS=y\nCONFIG_NVS=y\nCONFIG_SETTINGS_NVS=y\nCONFIG_SOC_FLASH_NRF_PARTIAL_ERASE_MS=6\n')
 mig_args=make_native('migration',fw/'ota_migration',fw/'ota_migration/prj.conf',[fw/'research/vimar-candidate.conf',mig_conf],[fw/'boards/nrf52840dk_nrf52840_ota.overlay',fw/'research/vimar-candidate.overlay'],['-DGENERATED_DIR='+str(mig_gen),'-DVIMAR_LOADER_CONTRACT_BINDINGS_HEADER='+str(all_header)])
 migration=sign('migration',native('migration',mig_args,0xc000,0xa2000),0xc000,0xa2000)
 for outer,inner in [('stockBootstrap','stockRestore'),('migration','recovery')]:
  offset=signed[outer].read_bytes().find(signed[inner].read_bytes())
  if offset<512:raise ValueError('actual signed embedded payload missing: '+outer)
  report.setdefault('embedded_bindings',{})[outer]=dict(component=inner,sha256=sha(signed[inner].read_bytes()),size=signed[inner].stat().st_size,offset=offset)
 save()
 # Actual signed compressed MAIN, no deployment index or live MQTT operation.
 compressed=art/'main.compressed.bin';commands=[paths['python'],ENCODER_ADAPTER,paths['imgtool'],'sign','--version',versions['main'],'--header-size','512','--slot-size','0xa2000','--overwrite-only','--align','1','-k',paths['private_key'],'--compression','lzma2armthumb','--compression-lzma-dictsize','32768','--compression-lzma-lp','0','--compression-lzma-lc','3','--compression-lzma-pb','2','--custom-tlv-file','0xa0',target,'--custom-tlv-file','0xa1',gen/'role-main.bin',raw['main'],compressed]
 run(commands,'carrier-sign.log');run([paths['python'],paths['imgtool'],'verify','-k',paths['public_key'],compressed],'carrier-verify.log')
 numbers=list(map(int,versions['main'].split('.')));file_version=(numbers[0]<<24)|(numbers[1]<<16)|(numbers[2]<<8);data=compressed.read_bytes();ota=struct.pack('<IHHHHHIH32sIHHHI',0x0beef11e,0x100,60,4,0xfff1,0x3085,file_version,2,b'Vimar30805 signed compressed OTA',66+len(data),1,1,0,len(data))+data
 (art/'main.ota').write_bytes(ota);(staging/'main.ota').write_bytes(ota);ota_meta=verify_zigbee_carrier(ota,main.read_bytes(),public,metadata['main']);report['ota']=dict(metadata=ota_meta,budget=split_stage_budget(main.stat().st_size,len(data),main.stat().st_size,recovery.stat().st_size),qualification='future matching runtime REC required; no currently installed source route claimed')
 descriptor=canonical(first_descriptor(loader,metadata,records,watchdog_handoff));first=staging/'first-install.json';first.write_bytes(descriptor)
 run(['openssl','dgst','-sha256','-sign',paths['private_key'],'-out',staging/'first-install.sig',first],'first-install-sign.log');verify_signature(public,(staging/'first-install.sig').read_bytes(),descriptor)
 policy=json.loads(Path(source_policy).read_text());allowed_sources=policy['allowedSourceSignedHashes'];legacy_recovery=policy['legacyRecoverySignedHashes']
 qualification=dict(schemaVersion=3,model='VIMAR30805',layoutVersion=2,loaderContracts=records,components={'loader':sha(loader),**{k:sha(v.read_bytes()) for k,v in signed.items()},'zigbeeOta':sha(ota)},commonFirstFlashVerified=False,stockRestoreVerified=False,**{field:False for field in (*REQUIRED_CHECKS,*SPLIT_REQUIRED_CHECKS)})
 q=write_json(out/'qualification-pending.json',qualification)
 first_meta=dict(file='first-install.json',size=len(descriptor),sha256=sha(descriptor),signatureFile='first-install.sig',signatureSha256=sha((staging/'first-install.sig').read_bytes()))
 proposed=dict(schemaVersion=3,minAppVersion='0.6.0',model='VIMAR30805',layoutVersion=2,identityProtocol=2,loaderContracts=records,legacyRecoverySignedHashes=legacy_recovery,targetRecoverySignedHash=metadata['recovery']['signedRegionSha256'],allowedSourceSignedHashes=allowed_sources,**metadata,zigbeeOta=ota_meta,qualificationSha256=sha(q.read_bytes()),firstInstall=first_meta)
 proposed['bundleId']=sha(canonical(proposed));(out/'proposed-manifest.UNSIGNED.json').write_bytes(canonical(proposed))
 release_input={k:v for k,v in proposed.items() if k not in {'bundleId','qualificationSha256','firstInstall',*metadata,'zigbeeOta'}}
 if watchdog_handoff is not None:release_input['watchdogHandoff']=watchdog_handoff
 release_input.update({k:dict(path=str(v.relative_to(out)),sha256=sha(v.read_bytes())) for k,v in signed.items()});release_input['loader']=dict(path='artifacts/loader.bin',sha256=sha(loader));release_input['zigbeeOta']=dict(path='artifacts/main.ota',sha256=sha(ota));release_input['qualification']=dict(path='qualification-pending.json',sha256=sha(q.read_bytes()));write_json(out/'release-input-QUALIFICATION-PENDING.json',release_input)
 report['first_install']=first_meta;report['generated_sha256']={str(p.relative_to(out)):sha(p.read_bytes()) for p in gen.rglob('*') if p.is_file()};report['staged_onezip_entries']={p.name:sha(p.read_bytes()) for p in staging.iterdir()};report['qualification']=public_record(q);report['status']='matched locally signed candidate executables and first-install descriptor; physical qualification pending; NO qualified release ZIP';report['builder_sha256']=sha(Path(__file__).read_bytes());save();return manifest

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--legacy-registry',type=Path,required=True);p.add_argument('--source-policy',type=Path,required=True);p.add_argument('--watchdog-handoff',choices=[WATCHDOG_HANDOFF]);p.add_argument('--multi-bond',action='store_true');p.add_argument('--release-version',help='coherent ordinary SemVer; requires watchdog+multi-bond and enables exact MAIN fault diagnostics');a=p.parse_args();print(build(a.output,a.legacy_registry,a.source_policy,a.watchdog_handoff,a.multi_bond,a.release_version))
if __name__=='__main__':main()
