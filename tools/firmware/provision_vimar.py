#!/usr/bin/env python3
"""Guided, device-bound Vimar provisioning. Never recover, mass-erase or write UICR."""
import argparse,fcntl,hashlib,json,os,re,subprocess,sys,time,zipfile
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
BACKUP_SIZES={'flash':0x100000,'uicr':4096,'ficr':4096}
KNOWN_DKS=set()  # Populated from explicit local --dk-id/environment configuration.
def sha(data):return hashlib.sha256(data).hexdigest()
def ieee(uid):return f'0xf4ce36{uid[0]&255:02x}{uid[1]:08x}'
def stock_ieee_evidence(uid,flash):
 candidate=ieee(uid);needle=bytes.fromhex(candidate[2:])[::-1]
 return {'candidate':candidate,'source':'FICR-derived stock convention',
         'stock_flash_little_endian_offsets':[m.start() for m in re.finditer(re.escape(needle),flash)],
         'active_record_decoded':False,
         'interpretation':'Byte matches corroborate the candidate; no active stock Zigbee record is decoded'}

def stable_target(observations):
 return bool(KNOWN_DKS) and len(observations)>=3 and len(set(observations[-3:]))==1 and observations[-1] not in KNOWN_DKS

def verify_backup(folder):
 result={}
 for name,size in BACKUP_SIZES.items():
  a=(folder/f'stock-{name}-a.bin').read_bytes();b=(folder/f'stock-{name}-b.bin').read_bytes()
  if len(a)!=size or len(b)!=size or a!=b:raise ValueError(f'Backup {name}: incomplete or inconsistent')
  result[name]={'size':size,'sha256':sha(a),'double_read_identical':True}
 return result

def expected_flash(before,image):
 if any(not 0<=a<len(before) for a in image):raise ValueError('Image outside FLASH; UICR/register writes forbidden')
 result=bytearray(before)
 for page in {a//4096*4096 for a in image}:result[page:page+4096]=b'\xff'*4096
 for a,value in image.items():result[a]=value
 return bytes(result)

def validate_flash_gate(folder,plan,uid):
 if tuple(plan['uid'])!=tuple(uid):raise ValueError('Target changed; flashing refused')
 if not plan.get('backup_verified') or not plan.get('restore_verified'):raise ValueError('Verified backup and BLE restore package required before flash')
 if sha((folder/'initial-install.hex').read_bytes())!=plan['image_sha256']:raise ValueError('Prepared image changed; flashing refused')
 if plan.get('ota_pair'):
  pair=plan['ota_pair'];report=Path(pair['qualification']['frozen_path']).read_bytes()
  if sha(report)!=pair['qualification']['sha256']:raise ValueError('Qualification evidence changed; flashing refused')
  from tools.firmware.ota_release import REQUIRED_CHECKS,SPLIT_REQUIRED_CHECKS
  checks=json.loads(report)
  if any(checks.get(k) is not True for k in (REQUIRED_CHECKS+(SPLIT_REQUIRED_CHECKS if pair.get('ota_profile')==2 else ()))) or any(checks.get(name+'_sha256')!=pair[name]['sha256'] for name in ['main','recovery']):raise ValueError('Qualification binding changed; flashing refused')
  if pair.get('ota_profile')==2:
   bound=pair['pair_bindings'];raw=Path(bound['frozen_path']).read_bytes()
   if sha(raw)!=bound['sha256']:raise ValueError('Pair bindings changed')
   binding=json.loads(raw);expected=(folder/'expected-flash.bin').read_bytes()
   if checks.get('ota_profile')!=2 or binding.get('allowed_loaders')!=checks.get('allowed_loaders') or binding.get('recovery_sha256')!=pair['recovery']['sha256'] or sha(expected[:0xc000]) not in binding.get('allowed_loaders',[]):raise ValueError('Split loader/recovery qualification mismatch')

def write_json(path,data):
 tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,indent=2)+'\n');tmp.replace(path)

def openocd(serial,commands,log,timeout=240):
 cmd=['openocd','-f','interface/jlink.cfg','-c',f'adapter serial {serial}','-c','transport select swd','-f','target/nrf52.cfg','-c','adapter speed 100','-c','init']
 cmd+=sum((['-c',c] for c in commands),[])+['-c','shutdown']
 with log.open('w') as f:
  result=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
 output=log.read_text()
 if result.returncode:raise RuntimeError(f'SWD failed; see {log}\n'+output[-1200:])
 return output

def guard(uid):
 return ('set ids [read_memory 0x10000060 32 2]; '
 f'if {{[lindex $ids 0] != {uid[0]:#x} || [lindex $ids 1] != {uid[1]:#x} || '
 '[lindex [read_memory 0x10000100 32 1] 0] != 0x52840 || '
 '[lindex [read_memory 0x10000104 32 1] 0] != 0x41414430} {error "Wrong Vimar target"}')

def path_arg(path):
 text=str(path.resolve())
 if any(c in text for c in ['"','\\','$','[',']','\n','\r']):raise ValueError('Unsupported Tcl path characters')
 return '"'+text+'"'

def detect(serial,timeout):
 folder=ROOT/'experiments/provisioning/detection';folder.mkdir(parents=True,exist_ok=True)
 deadline=time.monotonic()+timeout;observations=[]
 print('Collega UN dimmer Vimar al DK, solo alimentazione da banco. Attendo 3 identità SWD consecutive.',flush=True)
 while time.monotonic()<deadline:
  stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f');log=folder/f'{stamp}.log'
  try:
   raw=openocd(serial,['mdw 0x10000060 2','mdw 0x10000100 2'],log,15)
   ids=re.search(r'0x10000060:\s+([0-9a-fA-F]{8})\s+([0-9a-fA-F]{8})',raw)
   part=re.search(r'0x10000100:\s+00052840\s+41414430',raw)
   if not ids or not part:raise ValueError('Unsupported MCU/variant or incomplete identity')
   uid=tuple(int(x,16) for x in ids.groups())
   if uid in KNOWN_DKS:raise ValueError('DK interno rilevato: selezione target esterno non corretta')
   observations.append(uid);print(f'SWD OK: {uid[0]:08x}/{uid[1]:08x}, IEEE candidato {ieee(uid)}',flush=True)
   if stable_target(observations):return uid
  except (RuntimeError,ValueError,subprocess.TimeoutExpired) as exc:
   observations.clear();print(f'Attesa contatto: {exc}; log {log}',flush=True)
  time.sleep(0.5)
 raise TimeoutError('No stable external target; no flash attempted')

def backup(folder,uid,serial):
 result=folder/'backup-result.json'
 if result.exists():
  expected=json.loads(result.read_text());actual=verify_backup(folder)
  if actual!=expected:raise ValueError('Existing backup changed')
  ensure_stock_archive(folder)
  return actual
 # Preserve incomplete attempts, never overwrite captured evidence.
 for path in folder.glob('stock-*-?.bin'):
  attempt=folder/'partial'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f');attempt.mkdir(parents=True);path.rename(attempt/path.name)
 steps=[guard(uid),'halt','wait_halt 3000','adapter speed 1000']
 for suffix in ['a','b']:
  for kind,address in [('flash',0),('uicr',0x10001000),('ficr',0x10000000)]:
   steps.append(f'dump_image {path_arg(folder/f"stock-{kind}-{suffix}.bin")} {address:#x} {BACKUP_SIZES[kind]:#x}')
 print('Backup doppio FLASH/UICR/FICR in corso; target fermato. Non muovere i contatti.',flush=True)
 openocd(serial,steps,folder/'backup.log');record=verify_backup(folder);write_json(result,record)
 ensure_stock_archive(folder)
 return record

def ensure_stock_archive(folder):
 from tools.firmware.archive_tools import ensure_archive
 files={f'stock-{kind}.bin':folder/f'stock-{kind}-a.bin' for kind in BACKUP_SIZES}
 files['backup-result.json']=folder/'backup-result.json'
 ensure_archive(folder/'stock-backup.zip',files)

def validate_resume_selection(folder,main_override,ota_pair):
 path=folder/'plan.json'
 if not path.exists():
  frozen=folder/'ota-pair-provenance.json'
  if frozen.exists():
   previous=json.loads(frozen.read_text())
   if ota_pair is None or previous.get('manifest_sha256')!=ota_pair['manifest_sha256']:
    raise ValueError('Resume OTA selection requires the matching --ota-release after partial preparation')
  return
 plan=json.loads(path.read_text())
 if ota_pair is not None and plan.get('ota_pair',{}).get('manifest_sha256')!=ota_pair['manifest_sha256']:
  raise ValueError('Resume OTA selection differs from prepared plan')
 if main_override is not None:
  selected=[item for item in plan.get('components',[]) if item['name']=='main']
  if len(selected)!=1 or sha(main_override.read_bytes())!=selected[0]['sha256']:
   raise ValueError('Resume main selection differs from prepared plan')

def freeze_ota_pair(folder,pair):
 """Freeze validated bytes and qualification, never replacing earlier evidence."""
 from intelhex import IntelHex
 import io
 paths=[];files={}
 qualification=pair['qualification_data']
 if sha(qualification)!=pair['qualification']['sha256']:raise ValueError('Qualification snapshot SHA256 mismatch')
 provenance={k:pair[k] for k in ['manifest_path','manifest_sha256','qualification']}
 provenance['qualification']={**provenance['qualification'],'frozen_path':str((folder/'ota-qualification.json').resolve())}
 files[folder/'ota-qualification.json']=qualification
 if pair.get('ota_profile')==2:
  blob=pair['pair_bindings_data'];entry=pair['pair_bindings']
  if sha(blob)!=entry['sha256']:raise ValueError('Pair bindings snapshot mismatch')
  provenance['ota_profile']=2;provenance['pair_bindings']={**entry,'frozen_path':str((folder/'ota-pair-bindings.json').resolve())}
  files[folder/'ota-pair-bindings.json']=blob
 for name,base,capacity in [('main',0xc000,0xa4000),('recovery',0xb0000,0x40000)]:
  item=pair[name];data=item['data']
  if not data or len(data)>capacity or sha(data)!=item['sha256']:raise ValueError('Invalid frozen OTA component')
  binary=folder/f'qualified-{name}.signed.bin';hexfile=folder/f'qualified-{name}.signed.hex'
  h=IntelHex();h.frombytes(data,offset=base);stream=io.StringIO();h.write_hex_file(stream)
  files[binary]=data;files[hexfile]=stream.getvalue().encode()
  paths.append(hexfile);provenance[name]={'sha256':item['sha256'],'version':item['version']}
 record=folder/'ota-pair-provenance.json'
 files[record]=(json.dumps(provenance,indent=2)+'\n').encode()
 for path,content in files.items():
  if path.exists() and path.read_bytes()!=content:raise ValueError('Existing OTA evidence differs: '+str(path))
 for path,content in files.items():
  if not path.exists():path.write_bytes(content)
 return tuple(paths)

def prepare(folder,uid,serial,main,ota_pair=None):
 from intelhex import IntelHex
 from tools.firmware.restore_package import build_package
 ota_recovery=None
 if ota_pair is not None:main,ota_recovery=freeze_ota_pair(folder,ota_pair)
 from tools.firmware.toolchain_paths import toolchain_paths
 paths=toolchain_paths()
 subprocess.run([str(paths['python']),str(paths['imgtool']),'verify','-k',str(paths['public_key']),str(main)],check=True)
 record=backup(folder,uid,serial)
 restore=build_package(folder,uid)
 image=IntelHex();components=[]
 for name,path,low,high in [('loader',restore/'loader.hex',0,0xc000),('main',main,0xc000,0xb0000),('recovery',ota_recovery or restore/'recovery.signed.hex',0xb0000,0xf0000)]:
  h=IntelHex(str(path));addresses=h.addresses()
  if not addresses or any(not low<=a<high for a in addresses):raise ValueError(f'{name}: invalid component bounds')
  image.merge(h,overlap='error');components.append({'name':name,'path':str(path),'sha256':sha(path.read_bytes())})
 image.puts(0xf0000,b'\xff'*0x10000);image.write_hex_file(str(folder/'initial-install.hex'))
 before=(folder/'stock-flash-a.bin').read_bytes();expected=expected_flash(before,{a:image[a] for a in image.addresses()});(folder/'expected-flash.bin').write_bytes(expected)
 if ota_pair is not None and ota_pair.get('ota_profile')==2:
  bound=json.loads(ota_pair['pair_bindings_data'])
  if sha(expected[:0xc000]) not in bound.get('allowed_loaders',[]):raise ValueError('New loader not in the qualified split OTA registry; no device programmed')
 plan={'uid':list(uid),'ieee':ieee(uid),'ieee_evidence':stock_ieee_evidence(uid,before),'backup_verified':True,'restore_verified':True,'backup':record,'components':components,'image_sha256':sha((folder/'initial-install.hex').read_bytes()),'expected_sha256':sha(expected),'storage_reinitialized':True,'uicr_write':False,'mass_erase':False,'stage':'prepared'}
 if ota_pair is not None:plan['ota_pair']=json.loads((folder/'ota-pair-provenance.json').read_text())
 write_json(folder/'plan.json',plan);return plan

def flash(folder,plan,uid,serial):
 validate_flash_gate(folder,plan,uid);record=verify_backup(folder)
 if record!=plan['backup']:raise ValueError('Backup manifest changed')
 ensure_stock_archive(folder)
 from tools.firmware.restore_package import ensure_restore_archive
 ensure_restore_archive(folder/'restore')
 for item in plan['components']:
  if sha(Path(item['path']).read_bytes())!=item['sha256']:raise ValueError('Component changed')
 expected=(folder/'expected-flash.bin').read_bytes()
 if sha(expected)!=plan['expected_sha256']:raise ValueError('Expected image changed')
 print('FLASH in corso. Nessun recover/mass erase/UICR write. Segue rilettura completa.',flush=True)
 steps=[guard(uid),'reset halt','wait_halt 3000','adapter speed 1000',f'verify_image {path_arg(folder/"stock-flash-a.bin")} 0',f'verify_image {path_arg(folder/"stock-uicr-a.bin")} 0x10001000','if {[lindex [read_memory 0x4001e808 32 1] 0] != 0} {error "ACL active"}',f'program {path_arg(folder/"initial-install.hex")} verify',f'dump_image {path_arg(folder/"after-flash.bin")} 0 0x100000',f'dump_image {path_arg(folder/"after-uicr.bin")} 0x10001000 0x1000']
 openocd(serial,steps,folder/'flash.log')
 if (folder/'after-flash.bin').read_bytes()!=expected or (folder/'after-uicr.bin').read_bytes()!=(folder/'stock-uicr-a.bin').read_bytes():raise ValueError('Readback mismatch; target left halted')
 plan['stage']='verified_before_boot';write_json(folder/'plan.json',plan)
 openocd(serial,[guard(uid),'reset run'],folder/'boot.log',30)
 plan['stage']='flashed_boot_requested';plan['network_and_cold_boot']='pending';plan['physical_ble_factory_restore']='not yet tested on this unit';write_json(folder/'plan.json',plan)
 print(f'PASS: FLASH completo e UICR verificati. Boot richiesto. Dossier: {folder}',flush=True)

def main():
 global KNOWN_DKS
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--serial',default=os.environ.get('VIMAR_JLINK_SERIAL'),help='J-Link serial, or VIMAR_JLINK_SERIAL');parser.add_argument('--timeout',type=float,default=120)
 parser.add_argument('--resume',type=Path)
 images=parser.add_mutually_exclusive_group()
 images.add_argument('--main',type=Path,help='Ordinary signed main HEX; legacy recovery remains the default')
 images.add_argument('--ota-release',type=Path,help='Qualified signed main/recovery pair manifest; requires hardware qualification evidence')
 modes=parser.add_mutually_exclusive_group()
 modes.add_argument('--prepare-only',action='store_true')
 modes.add_argument('--backup-only',action='store_true',help='Double backup and ZIP only; no image selection, build or programming')
 parser.add_argument('--dk-id',action='append',default=[],metavar='UID0:UID1',help='Local DK DEVICEID to exclude; repeat for each DK, or set comma-separated VIMAR_DK_DEVICE_IDS. Required before hardware access.')
 parser.add_argument('--expected-id',help='Exact UID0:UID1 required for noninteractive --yes');parser.add_argument('--yes',action='store_true')
 args=parser.parse_args()
 if not args.serial or not re.fullmatch(r'[0-9]+',args.serial):parser.error('Provide --serial or VIMAR_JLINK_SERIAL with the J-Link serial')
 if args.timeout<=0:parser.error('--timeout must be positive')
 if args.yes and not args.expected_id:parser.error('--yes requires --expected-id UID0:UID1')
 if not args.main and not args.ota_release and not args.backup_only:
  release=os.environ.get('VIMAR_OTA_RELEASE')
  if release:args.ota_release=Path(release)
  else:parser.error('Select a qualified --ota-release (or VIMAR_OTA_RELEASE); legacy --main is explicit. Use --backup-only for stock backup.')
 if args.backup_only and (args.main or args.ota_release):parser.error('--backup-only does not accept firmware selection')
 ota_pair=None
 if args.ota_release:
  if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
  from tools.firmware.ota_release import load_ota_pair
  ota_pair=load_ota_pair(args.ota_release)
 main_image=args.main.resolve() if args.main else None
 dk_ids=args.dk_id+[value.strip() for value in os.environ.get('VIMAR_DK_DEVICE_IDS','').split(',') if value.strip()]
 if dk_ids:
  if any(not re.fullmatch(r'(?:0[xX])?[0-9a-fA-F]{8}:(?:0[xX])?[0-9a-fA-F]{8}',value) for value in dk_ids):parser.error('--dk-id / VIMAR_DK_DEVICE_IDS requires UID0:UID1, two8-digit hexadecimal words')
  KNOWN_DKS={tuple(int(word,16) for word in value.split(':')) for value in dk_ids}
 if not KNOWN_DKS:parser.error('Configure --dk-id UID0:UID1 or VIMAR_DK_DEVICE_IDS for each local DK before hardware access')
 (ROOT/'work').mkdir(exist_ok=True)
 with (ROOT/'work/provision-vimar.lock').open('w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  if args.resume:validate_resume_selection(args.resume.resolve(),args.main,ota_pair)
  uid=detect(args.serial,args.timeout)
  if args.expected_id and args.expected_id.lower()!=f'{uid[0]:08x}:{uid[1]:08x}':raise ValueError('Unexpected device, no backup/flash attempted')
  folder=args.resume.resolve() if args.resume else ROOT/'experiments/provisioning'/f'{uid[0]:08x}-{uid[1]:08x}'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
  folder.mkdir(parents=True,exist_ok=True)
  identity=folder/'identity.json'
  if identity.exists() and tuple(json.loads(identity.read_text())['uid'])!=uid:raise ValueError('Resume folder belongs to another device')
  if not identity.exists():write_json(identity,{'uid':list(uid),'ieee_candidate':ieee(uid),'probe_serial':args.serial})
  if args.backup_only:
   if (folder/'plan.json').exists():raise ValueError('Backup-only cannot reuse a firmware installation dossier')
   backup(folder,uid,args.serial)
   evidence=stock_ieee_evidence(uid,(folder/'stock-flash-a.bin').read_bytes())
   write_json(folder/'ieee-evidence.json',evidence)
   print(json.dumps(evidence),flush=True)
   print(f'Backup verificato, nessuna programmazione. Dossier: {folder}',flush=True)
   return
  planpath=folder/'plan.json'
  if planpath.exists():
   plan=json.loads(planpath.read_text())
   if plan['stage']=='flashed_boot_requested':print('Already flashed; dossier:',folder);return
   if plan['stage']=='verified_before_boot':
    validate_flash_gate(folder,plan,uid);print('Flash already verified. Device left halted: inspect dossier before explicitly restarting.');return
  else:plan=prepare(folder,uid,args.serial,main_image,ota_pair)
  print(json.dumps({k:plan[k] for k in ['uid','ieee','stage','storage_reinitialized','uicr_write']},indent=2),flush=True)
  if args.prepare_only:print('Preparazione completa; target fermato. Riprendi con --resume',folder);return
  if not args.yes and input(f'Conferma dimmer e IEEE attuale. Per flash scrivi {ieee(uid)}: ').strip()!=ieee(uid):print('Flash annullato; backup e preparazione conservati. Target fermato.');return
  flash(folder,plan,uid,args.serial)
if __name__=='__main__':
 try:main()
 except (Exception,KeyboardInterrupt) as exc:print(f'INTERROTTO: {exc}. Nessun recupero/erase automatico. Consulta il dossier; il target potrebbe essere fermato.',file=sys.stderr);sys.exit(1)
