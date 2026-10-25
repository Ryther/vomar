"""Opt-in common loader policy/SDK-shaped wrapper; not hardware crypto proof."""
import ctypes as c
from pathlib import Path
import struct
import subprocess
import zlib

import pytest
from test_loader_contract import Live, fixture as anchor_fixture

ROOT=Path(__file__).resolve().parents[3]
MODULE=ROOT/'firmware/common_restore_gate'
CORE=ROOT/'firmware/loader_contract'

class Image(c.Structure):
 _fields_=[('size',c.c_uint32),('payload_size',c.c_uint32),('role',c.c_uint8),('profile',c.c_uint8)]


def tlv(tag,value):return struct.pack('<HH',tag,len(value))+value

def area(magic,entries):return struct.pack('<HH',magic,len(entries)+4)+entries

def image_fixture(*,protected=None,unprotected=None,payload=None,flags=0):
 # Independent ordinary MCUboot shape. Fake crypto bytes are deliberate: the
 # parser cannot prove signatures and admission depends on fresh real boot_go.
 if payload is None:payload=struct.pack('<II',0x20010000,0xb0209)+bytes(1016)
 if protected is None:protected=tlv(0xa0,b'VIMAR30805\x02')+tlv(0xa1,b'\x04')
 prot=area(0x6908,protected) if protected else b''
 if unprotected is None:unprotected=tlv(0x10,b'H'*32)+tlv(1,b'K'*32)+tlv(0x22,b'\x30\x06\x02\x01\x01\x02\x01\x01')
 header=struct.pack('<IIHHII',0x96f3b83d,0,512,len(prot),len(payload),flags)+struct.pack('<BBHI',0,1,0,0)+bytes(484)
 return header+payload+prot+area(0x6907,unprotected)


@pytest.fixture(scope='module')
def lib(tmp_path_factory):
 out=tmp_path_factory.mktemp('common_restore_gate')/'policy.so'
 subprocess.run(['cc','-shared','-fPIC','-std=c11','-O1','-Wall','-Wextra','-Werror',
  '-I'+str(MODULE),'-I'+str(CORE),'-I'+str(ROOT/'firmware/ota'),
  str(MODULE/'common_restore_policy.c'),str(CORE/'loader_contract.c'),'-o',str(out)],check=True,capture_output=True)
 lib=c.CDLL(str(out))
 lib.common_restore_parse.argtypes=[c.c_void_p,c.c_size_t,c.POINTER(Image)]
 lib.common_restore_admit.argtypes=[c.c_bool,c.c_uint,c.c_uint32,c.c_void_p,c.c_size_t,c.c_void_p,c.c_size_t,c.POINTER(Live)]
 return lib


def parse(lib,blob):
 result=Image();c.memset(c.byref(result),0xa5,c.sizeof(result))
 rc=lib.common_restore_parse(blob,len(blob),c.byref(result))
 return rc,result


def test_canonical_ordinary_protected_restore_shape(lib):
 blob=image_fixture();rc,out=parse(lib,blob)
 assert rc==0 and (out.size,out.payload_size,out.role,out.profile)==(len(blob),1024,4,2)
 assert parse(lib,blob+b'\xff'*100)[0]==0
 counter=image_fixture(protected=tlv(0x50,struct.pack('<I',7))+tlv(0xa1,b'\x04')+tlv(0xa0,b'VIMAR30805\x02'))
 assert parse(lib,counter)[0]==0


@pytest.mark.parametrize('entries',[
 b'',tlv(0xa0,b'VIMAR30805\x02'),tlv(0xa1,b'\x04'),
 tlv(0xa0,b'VIMAR30805\x01')+tlv(0xa1,b'\x04'),
 tlv(0xa0,b'OTHER30805\x02')+tlv(0xa1,b'\x04'),
 *[tlv(0xa0,b'VIMAR30805\x02')+tlv(0xa1,bytes([role])) for role in [0,1,2,3,5,6]],
 tlv(0xa0,b'VIMAR30805\x02')+tlv(0xa1,b'\x04\0'),
 tlv(0xa0,b'VIMAR30805\x02')+tlv(0xa1,b''),
 tlv(0xa0,b'VIMAR30805\x02')*2+tlv(0xa1,b'\x04'),
 tlv(0xa0,b'VIMAR30805\x02')+tlv(0xa1,b'\x04')*2,
 tlv(0xa0,b'VIMAR30805\x02')+tlv(0xa1,b'\x04')+tlv(0xa2,b'x'),
 tlv(0xa0,b'VIMAR30805\x02')+tlv(0xa1,b'\x04')+tlv(0x50,b'x'),
 tlv(0xa0,b'VIMAR30805\x02')+tlv(0xa1,b'\x04')+tlv(0x50,b'1234')*2,
])
def test_missing_wrong_duplicate_or_unknown_protected_semantics_reject(lib,entries):
 rc,out=parse(lib,image_fixture(protected=entries))
 assert rc<0 and bytes(out)==bytes(c.sizeof(out))


@pytest.mark.parametrize('damage',['magic','load','header','protected_size','flags','reserved','short_payload',
 'stack_low','stack_high','stack_align','reset_even','reset_before','reset_after','unprot_header','truncated',
 'entry_crosses_protected','entry_crosses_unprotected','protected_magic','protected_total','role_unprotected','target_unprotected',
 'duplicate_hash','duplicate_key','duplicate_sig','missing_hash','missing_key','missing_sig','unknown_unprotected','extent'])
def test_malformed_headers_vectors_extent_and_tlv_placement_reject(lib,damage):
 blob=bytearray(image_fixture());start=512+1024;end=start+struct.unpack_from('<H',blob,10)[0]
 if damage=='magic':blob[0]^=1
 if damage=='load':blob[4]=1
 if damage=='header':struct.pack_into('<H',blob,8,256)
 if damage=='protected_size':struct.pack_into('<H',blob,10,0xffff)
 if damage=='flags':struct.pack_into('<I',blob,16,0xc00)
 if damage=='reserved':blob[28]=1
 if damage=='short_payload':blob=bytearray(image_fixture(payload=b'1234'))
 if damage=='stack_low':struct.pack_into('<I',blob,512,0x20000000)
 if damage=='stack_high':struct.pack_into('<I',blob,512,0x20040008)
 if damage=='stack_align':struct.pack_into('<I',blob,512,0x20010001)
 if damage=='reset_even':struct.pack_into('<I',blob,516,0xb0208)
 if damage=='reset_before':struct.pack_into('<I',blob,516,0xb01ff)
 if damage=='reset_after':struct.pack_into('<I',blob,516,0xb0601)
 if damage=='unprot_header':blob[end]^=1
 if damage=='truncated':blob=blob[:-1]
 if damage=='entry_crosses_protected':struct.pack_into('<H',blob,start+6,0xffff)
 if damage=='entry_crosses_unprotected':struct.pack_into('<H',blob,end+6,0xffff)
 if damage=='protected_magic':blob[start]^=1
 if damage=='protected_total':blob[start+2]^=1
 if damage.endswith('_unprotected') and damage in ['role_unprotected','target_unprotected','unknown_unprotected']:
  extra=tlv(0xa1,b'\x04') if damage=='role_unprotected' else tlv(0xa0,b'VIMAR30805\x02') if damage=='target_unprotected' else tlv(0x73,b'1234')
  blob.extend(extra);struct.pack_into('<H',blob,end+2,len(blob)-end)
 if damage.startswith('duplicate_') or damage.startswith('missing_'):
  field=damage.split('_')[1];values={'hash':tlv(0x10,b'H'*32),'key':tlv(1,b'K'*32),'sig':tlv(0x22,b'\x30\x06\x02\x01\x01\x02\x01\x01')}
  entries=b''.join(value for key,value in values.items() if not (damage.startswith('missing_') and key==field))
  if damage.startswith('duplicate_'):entries+=values[field]
  blob=bytearray(image_fixture(unprotected=entries))
 if damage=='extent':
  payload=struct.pack('<II',0x20010000,0xb0209)+bytes(0x3f000-512)
  blob=bytearray(image_fixture(payload=payload))
 rc,out=parse(lib,bytes(blob));assert rc<0 and bytes(out)==bytes(c.sizeof(out))


@pytest.mark.parametrize('valid,device,offset',[(False,0,0xb0000),(True,1,0xb0000),(True,0,0xc000),(True,0,0xb0001)])
def test_fresh_real_signature_and_exact_selected_device_slot_are_necessary(lib,valid,device,offset):
 anchor,live,_,_=anchor_fixture();blob=image_fixture()
 assert lib.common_restore_admit(valid,device,offset,blob,len(blob),anchor,len(anchor),c.byref(live))<0


def test_verified_slot_and_real_anchor_are_jointly_required(lib):
 anchor,live,_,_=anchor_fixture();blob=image_fixture()
 assert lib.common_restore_admit(True,0,0xb0000,blob,len(blob),anchor,len(anchor),c.byref(live))==0
 corrupt=bytearray(anchor);corrupt[252]^=1
 assert lib.common_restore_admit(True,0,0xb0000,blob,len(blob),bytes(corrupt),4096,c.byref(live))<0
 live.uicr_sha256[0]^=1
 assert lib.common_restore_admit(True,0,0xb0000,blob,len(blob),anchor,len(anchor),c.byref(live))<0


def test_parse_output_aliases_selected_image_safely(lib):
 blob=image_fixture();storage=c.create_string_buffer(blob)
 out=c.cast(storage,c.POINTER(Image))
 assert lib.common_restore_parse(storage,len(blob),out)==0
 assert out.contents.size==len(blob) and out.contents.role==4


CONFIG_REQUIRED=['CONFIG_MCUBOOT','CONFIG_SOC_NRF52840','CONFIG_BOOT_FIRMWARE_LOADER',
 'CONFIG_BOOT_VALIDATE_SLOT0','CONFIG_BOOT_SIGNATURE_TYPE_ECDSA_P256','CONFIG_BOOT_USE_CC310',
 'CONFIG_BOOT_USE_NRF_CC310_BL','CONFIG_BOOT_FIH_PROFILE_OFF','CONFIG_FPROTECT','CONFIG_MCUBOOT_USE_TLV_ALLOW_LIST']
CONFIG_FORBIDDEN=['CONFIG_BOOT_VALIDATE_SLOT0_ONCE','CONFIG_BOOT_BYPASS_KEY_MATCH','CONFIG_NCS_MCUBOOT_LCS_AWARE',
 'CONFIG_BOOT_SIGNATURE_TYPE_NONE','CONFIG_VIMAR_STOCK_RESTORE_GATE','CONFIG_MCUBOOT_ACTION_HOOKS',
 'CONFIG_BOOT_IMAGE_ACCESS_HOOKS','CONFIG_BOOT_GO_HOOKS','CONFIG_BOOT_FLASH_AREA_HOOKS',
 'CONFIG_BOOT_ENCRYPT_IMAGE','CONFIG_BOOT_HW_KEY','CONFIG_NCS_BOOT_SIGNATURE_USING_ITS',
 'CONFIG_BOOT_SIGNATURE_USING_KMU','CONFIG_BOOT_SWAP_USING_SCRATCH','CONFIG_BOOT_SWAP_USING_MOVE',
 'CONFIG_BOOT_SWAP_USING_OFFSET','CONFIG_BOOT_UPGRADE_ONLY','CONFIG_MCUBOOT_COMPRESSED_IMAGE_SUPPORT_ENABLED']


def adapter_headers(base):
 headers={
 'bootutil/bootutil.h':'#include <stdint.h>\ntypedef int fih_ret;\nstruct boot_rsp {const void*br_hdr;uint8_t br_flash_dev_id;uint32_t br_image_off;};\n',
 'bootutil/fault_injection_hardening.h':'#define FIH_FAILURE -1\n#define FIH_SUCCESS 0\n#define FIH_DECLARE(n,v) int n=v\n#define FIH_CALL(f,r,...) r=f(__VA_ARGS__)\n#define FIH_EQ(a,b) ((a)==(b))\n#define FIH_RET(r) return r\n',
 'bootutil/crypto/sha.h':'#include <stdint.h>\n#define IMAGE_HASH_SIZE 32\ntypedef int bootutil_sha_context;\nint bootutil_sha_init(int*);int bootutil_sha_update(int*,const void*,uint32_t);int bootutil_sha_finish(int*,uint8_t*);int bootutil_sha_drop(int*);\n',
 'fprotect.h':'#include <stdint.h>\n#include <stddef.h>\nint fprotect_area(uint32_t,size_t);\n',
 'hal/nrf_ficr.h':'#include <stdint.h>\ntypedef struct {uint32_t CODEPAGESIZE,CODESIZE,DEVICEID[2];struct {uint32_t PART,VARIANT,RAM;} INFO;} NRF_FICR_Type;\nextern NRF_FICR_Type test_ficr;\n#define NRF_FICR (&test_ficr)\nstatic inline uint32_t nrf_ficr_codepagesize_get(const NRF_FICR_Type*p){return p->CODEPAGESIZE;}\nstatic inline uint32_t nrf_ficr_codesize_get(const NRF_FICR_Type*p){return p->CODESIZE;}\nstatic inline uint32_t nrf_ficr_deviceid_get(const NRF_FICR_Type*p,uint32_t n){return p->DEVICEID[n];}\n',
 }
 for name,value in headers.items():
  file=base/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text(value)
 return ['-I'+str(base),'-I'+str(MODULE),'-I'+str(CORE)]


def test_actual_sdk_adapter_clears_private_authority_and_delegates_errors(tmp_path):
 includes=adapter_headers(tmp_path);out=tmp_path/'adapter'
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=undefined','-fno-sanitize-recover=all',
  *['-D'+name+'=1' for name in CONFIG_REQUIRED],*includes,str(MODULE/'common_restore_gate.c'),
  str(Path(__file__).with_name('common_restore_gate_adapter_test.c')),'-o',str(out)],check=True,capture_output=True)
 subprocess.run([str(out)],check=True)


@pytest.mark.parametrize('remove,add',[(name,None) for name in CONFIG_REQUIRED]+[(None,name) for name in CONFIG_FORBIDDEN])
def test_adapter_rejects_unaudited_validation_crypto_hooks_and_simultaneous_wrappers(tmp_path,remove,add):
 includes=adapter_headers(tmp_path)
 defines=[name for name in CONFIG_REQUIRED if name!=remove]+([add] if add else [])
 result=subprocess.run(['cc','-std=c11',*['-D'+name+'=1' for name in defines],*includes,
  '-c',str(MODULE/'common_restore_gate.c'),'-o',str(tmp_path/'unsupported.o')],capture_output=True,text=True)
 assert result.returncode!=0
 assert 'common restore gate' in result.stderr.lower()


@pytest.mark.parametrize('bytes_used,passes',[(0xafff,True),(0xb000,True),(0xb001,False),(0xbfff,False)])
def test_link_reservation_covers_initialized_data_extent(tmp_path,bytes_used,passes):
 # A data-only load image proves that code-size-only checking is insufficient.
 source=tmp_path/'data.s';source.write_text('.section .data\n.byte 1\n.zero '+str(bytes_used-1)+'\n')
 obj=tmp_path/'data.o';subprocess.run(['cc','-c',str(source),'-o',str(obj)],check=True,capture_output=True)
 script=tmp_path/'layout.ld';script.write_text('SECTIONS { . = 0; .text : { *(.text*) *(.rodata*) } .data : { *(.data*) } _flash_used = .; }\nINCLUDE '+str(MODULE/'anchor_reservation.ld')+'\n')
 result=subprocess.run(['ld','-T',str(script),str(obj),'-o',str(tmp_path/'image')],capture_output=True,text=True)
 assert (result.returncode==0)==passes
 if not passes:assert 'reserved anchor page' in result.stderr


from test_image_roles import crypto


@pytest.mark.parametrize('role',[1,2,3,4,5])
def test_real_ephemeral_signature_and_pure_role_admission_are_separate_necessary_layers(lib,crypto,role):
 from test_image_roles import fixture, verify
 anchor,live,_,_=anchor_fixture()
 ordinary,_=fixture(crypto,role=bytes([role]),vector_base=0xb0000)
 verified,metadata=verify(crypto,ordinary)
 assert verified==0 and metadata.authenticated_role==role
 rc=lib.common_restore_admit(verified==0,0,0xb0000,ordinary,len(ordinary),anchor,len(anchor),c.byref(live))
 assert (rc==0)==(role==4)


@pytest.mark.parametrize('damage',['payload','signature','wrong_key'])
def test_role_header_cannot_replace_actual_signature_success(lib,crypto,damage):
 from test_image_roles import fixture, verify
 from cryptography.hazmat.primitives.asymmetric import ec
 anchor,live,_,_=anchor_fixture()
 signing=crypto if damage!='wrong_key' else (crypto[0],ec.generate_private_key(ec.SECP256R1()),crypto[2])
 ordinary,_=fixture(signing,role=b'\x04',vector_base=0xb0000)
 blob=bytearray(ordinary)
 if damage=='payload':blob[600]^=1
 if damage=='signature':blob[-1]^=1
 # Shape/role remains valid, while real independent OpenSSL crypto refuses it.
 assert parse(lib,bytes(blob))[0]==0
 verified,_=verify(crypto,bytes(blob))
 assert verified<0
 assert lib.common_restore_admit(verified==0,0,0xb0000,bytes(blob),len(blob),anchor,4096,c.byref(live))<0


def test_adapter_rejects_non_sha256_image_backend(tmp_path):
 includes=adapter_headers(tmp_path);sha=tmp_path/'bootutil/crypto/sha.h'
 sha.write_text(sha.read_text().replace('IMAGE_HASH_SIZE 32','IMAGE_HASH_SIZE 64'))
 result=subprocess.run(['cc','-std=c11',*['-D'+name+'=1' for name in CONFIG_REQUIRED],*includes,
  '-c',str(MODULE/'common_restore_gate.c'),'-o',str(tmp_path/'unsupported.o')],capture_output=True,text=True)
 assert result.returncode!=0 and 'requires SHA256' in result.stderr
