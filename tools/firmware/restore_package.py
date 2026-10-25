"""Device-bound restore artifacts; build only, never access hardware."""
import hashlib,json,re,shutil,struct,subprocess,zipfile,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
TEMPLATES=Path(__file__).with_name('restore_templates')
def sha(data):return hashlib.sha256(data).hexdigest()
def addresses(uid,ficr):
 low,high=struct.unpack_from('<II',ficr,0xa4)
 native=f'{((high&0xffff)|0xc000):04X}{low:08X}'
 normal=':'.join(native[i:i+2] for i in range(0,12,2))
 custom=f'C5{uid[0]&255:02X}{uid[1]:08X}'
 return normal,':'.join(custom[i:i+2] for i in range(0,12,2))
def render_sources(folder,uid):
 out=folder/'restore';out.mkdir(exist_ok=True);(out/'bootstrap').mkdir(exist_ok=True);(out/'logs').mkdir(exist_ok=True)
 b=(folder/'stock-flash-a.bin').read_bytes();u=(folder/'stock-uicr-a.bin').read_bytes();f=(folder/'stock-ficr-a.bin').read_bytes()
 if len(b)!=0x100000 or len(u)!=4096 or len(f)!=4096:raise ValueError('Incomplete device backup')
 if b[0xb0000:0xef000]!=b'\xff'*0x3f000:raise ValueError('Stock scratch region is not erased; this BLE restoration layout is unsupported')
 if tuple(struct.unpack_from('<II',f,0x60))!=tuple(uid):raise ValueError('FICR identity does not match package target')
 variant=struct.unpack_from('<I',f,0x104)[0]
 if variant in (0,0xffffffff):raise ValueError('FICR chip variant is missing')
 normal,restore=addresses(uid,f);transforms=[]
 for row in json.loads((TEMPLATES/'provenance.json').read_text()):
  name=row['template'];source=TEMPLATES/name;data=source.read_bytes()
  if sha(data)!=row['sha256']:raise ValueError('Restore template hash changed: '+name)
  s=data.decode()
  bindings={'@VIMAR_UID0@':f'{uid[0]:08x}','@VIMAR_UID1@':f'{uid[1]:08x}',
            '@VIMAR_RESTORE_BLE_ADDRESS@':restore,'@VIMAR_NORMAL_BLE_ADDRESS@':normal,
            '@VIMAR_STOCK_FLASH_SHA256@':sha(b),'@VIMAR_CHIP_VARIANT@':f'{variant:08x}'}
  for token,value in bindings.items():s=s.replace(token,value)
  if re.search(r'@VIMAR_[A-Z0-9_]+@',s):raise ValueError('Unresolved restore template binding: '+name)
  if name=='restorer.overlay':s='#include "'+str(ROOT/'firmware/boards/ota-partitions.dtsi')+'"\n/ { chosen { zephyr,code-partition = &slot1_partition; }; };\n'
  (out/name).write_text(s);transforms.append({'source':str(source.relative_to(ROOT)),'source_sha256':sha(data),'destination':name,'sha256':sha(s.encode())})
 pages=['{'+','.join(hex(c) for c in hashlib.sha256(b[i:i+4096]).digest())+'},' for i in range(0,len(b),4096)]
 mac=','.join(hex(int(x,16)) for x in reversed(restore.split(':')))
 (out/'probe_manifest.h').write_text('#ifndef PROBE_MANIFEST_H\n#define PROBE_MANIFEST_H\n#include <stdint.h>\n'+f'#define PROBE_UID0 {uid[0]:#x}U\n#define PROBE_UID1 {uid[1]:#x}U\n#define PROBE_MAC_BYTES '+'{'+mac+'}\nstatic const uint8_t expected_pages[256][32] = {\n'+'\n'.join(pages)+'\n};\nstatic const uint8_t expected_uicr[32] = {'+','.join(hex(c) for c in hashlib.sha256(u).digest())+'};\n#endif\n')
 for kind in ['flash','uicr','ficr']:shutil.copyfile(folder/f'stock-{kind}-a.bin',out/f'stock-{kind}.bin')
 manifest={'deviceid':[f'{x:08x}' for x in uid],'chip_variant':variant,'normal_ble_address':normal,'restore_ble_address':restore,'restore_ble_passkey':824005,'flash_sha256':sha(b),'uicr_sha256':sha(u),'transformations':transforms,'probe_manifest_transformation':'256 SHA256 page digests, original UICR digest, exact FICR UID and chip revision, unique restorer BLE address'}
 (out/'source-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');return out,manifest

def build_package(folder,uid):
 from intelhex import IntelHex
 from tools.firmware.validate_recovery import validate_uicr_preservation,read_config,validate_image
 from tools.firmware.toolchain_paths import toolchain_paths
 paths=toolchain_paths()
 out=folder/'restore';cached=out/'artifact-manifest.json'
 if cached.exists():
  if (out/'signing-public.pem').read_bytes()!=paths['public_key'].read_bytes():raise ValueError('Cached restore signing key differs from configured key')
  m=json.loads(cached.read_text())
  ficr=(folder/'stock-ficr-a.bin').read_bytes()
  if len(ficr)!=4096 or m.get('chip_variant',0x41414430)!=struct.unpack_from('<I',ficr,0x104)[0]:raise ValueError('Cached package chip variant differs from backup; rebuild in a fresh directory')
  if m['deviceid']!=[f'{x:08x}' for x in uid] or m['flash_sha256']!=sha((folder/'stock-flash-a.bin').read_bytes()):raise ValueError('Cached package belongs to different backup/target')
  for name,item in m['artifacts'].items():
   if sha((out/name).read_bytes())!=item['sha256']:raise ValueError('Cached package artifact changed')
  ensure_restore_archive(out)
  return out
 out,m=render_sources(folder,uid);sdk=paths['sdk'];python=paths['python'];west=paths['west'];img=paths['imgtool'];key=paths['private_key'];pub=paths['public_key'];commands=[];prefix=ROOT/'work/provision-builds'/f'{uid[0]:08x}-{uid[1]:08x}';prefix.mkdir(parents=True,exist_ok=True)
 def run(stage,cmd):
  print('Ripristino BLE:',stage,flush=True);commands.append({'stage':stage,'command':list(map(str,cmd))});(out/'build-commands.json').write_text(json.dumps(commands,indent=2)+'\n')
  with (out/'logs'/f'{stage}.log').open('w') as log:subprocess.run(list(map(str,cmd)),cwd=sdk,stdout=log,stderr=subprocess.STDOUT,check=True)
 def build(stage,source,overlay,version):
  dest=prefix/stage
  run(stage,[west,'build','--pristine','--no-sysbuild','-b','nrf52840dk/nrf52840',source,'-d',dest,'--','-DDTC_OVERLAY_FILE='+';'.join(map(str,[overlay,ROOT/'firmware/research/vimar-candidate.overlay'])),'-DEXTRA_CONF_FILE='+str(ROOT/'firmware/research/vimar-candidate.conf'),'-DCONFIG_MCUBOOT_SIGNATURE_KEY_FILE="'+str(key)+'"','-DCONFIG_MCUBOOT_IMGTOOL_SIGN_VERSION="'+version+'"'])
  signed=dest/'zephyr/zephyr.signed.bin';run(stage+'-verify',[python,img,'verify','-k',pub,signed]);return signed
 restorer=build('restorer',out,out/'restorer.overlay','0.6.4+0');data=restorer.read_bytes();validate_image(data,0xb0000,0x3f000);blob=data+b'\xff'*((-len(data))%4)
 (out/'bootstrap/restorer_blob.h').write_text('#define RESTORER_CRC32 '+hex(zlib.crc32(blob))+'U\nstatic const unsigned char restorer_blob[] __aligned(4) = {\n'+'\n'.join(','.join(hex(c) for c in blob[i:i+16])+',' for i in range(0,len(blob),16))+'\n};\n')
 bootstrap=build('bootstrap',out/'bootstrap',ROOT/'firmware/boards/nrf52840dk_nrf52840_ota.overlay','0.6.5+0');validate_image(bootstrap.read_bytes(),0xc000,0xa4000)
 (out/'gate.conf').write_text('CONFIG_VIMAR_STOCK_RESTORE_GATE=y\nCONFIG_VIMAR_STOCK_RESTORER_SHA256="'+sha(data)+'"\nCONFIG_VIMAR_STOCK_RESTORER_SIZE='+str(len(data))+'\n');(out/'debounce.conf').write_text('CONFIG_BOOT_FIRMWARE_LOADER_DETECT_DELAY=500\n')
 dest=prefix/'loader'
 run('loader',[west,'build','--pristine','--sysbuild','-b','nrf52840dk/nrf52840',ROOT/'firmware','-d',dest,'--','-DSB_CONFIG_BOOT_SIGNATURE_KEY_FILE="'+str(key)+'"','-DFILE_SUFFIX=ota','-Dmcuboot_EXTRA_CONF_FILE='+';'.join(map(str,[ROOT/'firmware/research/loader-software-recovery.conf',ROOT/'firmware/research/vimar-candidate.conf',out/'gate.conf',out/'debounce.conf'])),'-Dmcuboot_ZEPHYR_EXTRA_MODULES='+str(ROOT/'firmware/restore_gate'),'-DVIMAR_RESEARCH_BOARD_OVERLAY='+str(ROOT/'firmware/research/vimar-candidate.overlay'),'-Dvimar_recovery_EXTRA_CONF_FILE='+str(ROOT/'firmware/research/vimar-candidate.conf')])
 folders={'restorer':restorer.parent,'bootstrap':bootstrap.parent,'loader':dest/'mcuboot/zephyr','recovery':dest/'vimar_recovery/zephyr'}
 configs={n:read_config(z/'.config') for n,z in folders.items()};defines={n:set(re.findall(r'-D([A-Za-z0-9_]+)',(z.parent/'build.ninja').read_text())) for n,z in folders.items()};validate_uicr_preservation(configs,defines)
 run('ldo-check',[python,out/'check_ldo.py']+[z.parent for z in folders.values()])
 for name,config in configs.items():
  if config.get('CONFIG_NORDIC_QSPI_NOR')=='y':raise ValueError('QSPI enabled in '+name)
 if configs['loader'].get('CONFIG_FPROTECT')!='y' or configs['loader'].get('CONFIG_BOOT_VALIDATE_SLOT0')!='y':raise ValueError('Loader validation/protection disabled')
 if configs['loader'].get('CONFIG_VIMAR_STOCK_RESTORER_SHA256','').strip(chr(34))!=sha(data):raise ValueError('Loader allowlist mismatch')
 for source,name in [(restorer,'restorer.signed.bin'),(bootstrap,'restore-bootstrap.signed.bin'),(dest/'mcuboot/zephyr/zephyr.hex','loader.hex'),(dest/'vimar_recovery/zephyr/zephyr.signed.hex','recovery.signed.hex'),(pub,'signing-public.pem')]:shutil.copyfile(source,out/name)
 recovery=IntelHex(str(out/'recovery.signed.hex'));validate_image(bytes(recovery.tobinarray(start=0xb0000,end=recovery.maxaddr())),0xb0000,0x40000)
 run('recovery-verify',[python,img,'verify','-k',pub,out/'recovery.signed.hex'])
 m['commands']=commands;m['artifacts']={name:{'sha256':sha((out/name).read_bytes()),'size':(out/name).stat().st_size} for name in ['restorer.signed.bin','restore-bootstrap.signed.bin','loader.hex','recovery.signed.hex','signing-public.pem']};m['status']='Build verified; physical BLE stock restoration not yet qualified on this unit'
 (out/'README.txt').write_text('Device-specific full original FLASH restoration. Never use on another unit.\nUID: '+str(m['deviceid'])+'\nOriginal FLASH SHA256: '+m['flash_sha256']+'\n1. Enter independent BLE recovery: both keys5s, or Zigbee enter_recovery=true.\n2. Pair recovery at '+m['normal_ble_address']+' with passkey824005 (bluetoothctl).\n3. python enter_restore_via_ble.py --address '+m['normal_ble_address']+'\n4. python restore_via_ble.py info\n5. python restore_via_ble.py restore\nDependencies: bleak, smpclient, intelhex, dbus-fast. See workspace venv for tested versions.\nThe restore action rewrites original FLASH and replaces custom firmware. UICR is verified, never written.\nPhysical restoration is not claimed until tested on this unit. Keep SWD backup.\n')
 m['package_files']={name:sha((out/name).read_bytes()) for name in RESTORE_FILES if name!='artifact-manifest.json'}
 cached.write_text(json.dumps(m,indent=2)+'\n')
 ensure_restore_archive(out)
 return out

RESTORE_FILES=['README.txt','artifact-manifest.json','restore-bootstrap.signed.bin','restorer.signed.bin','loader.hex','recovery.signed.hex','signing-public.pem','stock-flash.bin','stock-uicr.bin','stock-ficr.bin','enter_restore_via_ble.py','restore_via_ble.py','research_console.py']
def ensure_restore_archive(out):
 from tools.firmware.archive_tools import ensure_archive
 m=json.loads((out/'artifact-manifest.json').read_text())
 hashes=m.get('package_files',{})
 if set(hashes)!=set(RESTORE_FILES)-{'artifact-manifest.json'}:raise ValueError('Incomplete restoration archive manifest; rebuild package')
 for name,digest in hashes.items():
  if sha((out/name).read_bytes())!=digest:raise ValueError('Restoration package file changed: '+name)
 logs=out/'logs';logs.mkdir(exist_ok=True);(logs/'.keep').touch(exist_ok=True)
 ensure_archive(out.parent/'ble-stock-restore.zip',{**{name:out/name for name in RESTORE_FILES},'logs/.keep':logs/'.keep'})
