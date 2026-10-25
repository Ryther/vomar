"""Common RESTORE consumer: independent full backup, local identity and real SHA256.

No target IO, production key, signed release or per-device firmware generation.
"""
import ctypes as c
import hashlib
from pathlib import Path
import struct
import subprocess
import zlib
import re

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'firmware/common_restore'
CORE = ROOT / 'firmware/loader_contract'
SIZE, PAGE, BOOT = 0x100000, 4096, 0xc000
DOMAIN = b'VIMAR30805-LOADER-CODE44K-ANCHOR1\0'

class Live(c.Structure):
    _fields_ = [('part', c.c_uint32), ('variant', c.c_uint32), ('uid', c.c_uint32 * 2),
                ('flash_size', c.c_uint32), ('page_size', c.c_uint32), ('ram_size', c.c_uint32),
                ('uicr_size', c.c_uint32), ('uicr_sha256', c.c_uint8 * 32)]

@pytest.fixture(scope='module')
def lib(tmp_path_factory):
    out = tmp_path_factory.mktemp('common_restore_consumer') / 'consumer.so'
    sources = [CORE / 'loader_contract.c', CORE / 'loader_restore_complete.c',
               Path(__file__).with_name('common_restore_consumer_host.c')]
    if (SOURCE / 'common_restore.c').exists(): sources += [SOURCE / 'common_restore.c']
    for name in ['radio_identity.c','protocol.c']:
        if (SOURCE/name).exists():sources.append(SOURCE/name)
    key=ec.generate_private_key(ec.SECP256R1())
    der=key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    if (SOURCE/'bootstrap.c').exists():
        crypto=(ROOT/'firmware/ota/ota_image.c').read_text()
        for name,value in [('public_key',key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)),('public_key_hash',hashlib.sha256(der).digest())]:
            crypto,n=re.subn(r'(static const uint8_t '+name+r'\[\d+\] = \{).*?\};',lambda m:m[1]+','.join(hex(v) for v in value)+'};',crypto,count=1,flags=re.S);assert n==1
        host=out.parent/'test_key_ota.c';host.write_text(crypto)
        sources += [SOURCE/'bootstrap.c',ROOT/'firmware/common_restore_gate/common_restore_policy.c',host]
    subprocess.run(['cc', '-shared', '-fPIC', '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror',
                    '-Werror=vla', '-Wno-deprecated-declarations','-DOTA_IMAGE_HOST','-DOTA_IMAGE_AUTH_ONLY','-DCOMMON_RESTORE_HOST', '-fsanitize=undefined', '-fno-sanitize-recover=all',
                    '-I'+str(SOURCE), '-I'+str(CORE),'-I'+str(ROOT/'firmware/ota'),'-I'+str(ROOT/'firmware/common_restore_gate'), *map(str,sources), '-lcrypto', '-o', str(out)],
                   check=True, capture_output=True)
    lib=c.CDLL(str(out))
    lib.restore_open.argtypes=[c.c_void_p,c.c_size_t,c.POINTER(Live),c.c_void_p,c.c_int,c.c_uint64,c.c_uint32]
    lib.restore_chunk.argtypes=[c.c_uint64,c.c_uint32,c.c_uint32,c.c_uint32,c.c_void_p,c.c_size_t]
    lib.restore_page.argtypes=[c.c_uint64,c.c_uint32,c.c_uint32,c.c_uint32,c.c_uint32,c.c_void_p,c.c_size_t]
    lib.restore_begin.argtypes=lib.restore_prepare.argtypes=lib.restore_final_request.argtypes=[c.c_uint64,c.c_uint32,c.c_uint32]
    lib.restore_commit.argtypes=[c.c_uint64,c.c_uint32,c.c_uint32,c.c_uint32]
    lib.restore_final_execute.argtypes=[c.c_uint64,c.c_uint32]
    lib.restore_cancel.argtypes=[c.c_uint64]
    lib.restore_bootstrap_open.argtypes=[c.c_void_p,c.c_size_t,c.POINTER(Live),c.c_void_p,c.c_void_p,c.c_size_t]
    lib.restore_bootstrap_copy.argtypes=[c.c_uint32]
    lib.restore_radio.argtypes=[c.c_uint32,c.c_uint32,c.c_void_p,c.c_uint,c.c_void_p]
    lib.restore_protocol.argtypes=[c.c_void_p,c.c_size_t]
    lib.restore_reply.argtypes=[c.c_void_p]
    lib.restore_io_fault.argtypes=[c.c_uint32,c.c_uint,c.c_uint]
    lib.test_key=key;lib.test_keyhash=hashlib.sha256(der).digest()
    return lib

@pytest.fixture
def backup(lib):
    original=bytearray(bytes((i*29+(i//PAGE)*7)&255 for i in range(SIZE)))
    original[0xb0000:0xef000]=b'\xff'*0x3f000
    original=bytes(original);table=b''.join(hashlib.sha256(original[i:i+PAGE]).digest() for i in range(0,SIZE,PAGE))
    uicr=hashlib.sha256(b'original UICR').digest()
    live=Live(0x52840,0x41414430,(c.c_uint32*2)(0x11223344,0x55667788),SIZE,PAGE,0x40000,PAGE,(c.c_uint8*32).from_buffer_copy(uicr))
    code=bytes((i*13+41)&255 for i in range(0xb000))
    anchor=bytearray(b'\xff'*PAGE)
    struct.pack_into('<4sHH11I12s',anchor,0,b'VAR1',1,256,1,2,0x52840,live.variant,*live.uid,SIZE,PAGE,0x40000,PAGE,8192,b'VIMAR30805\0\0')
    anchor[64:160]=hashlib.sha256(original).digest()+uicr+hashlib.sha256(table).digest()
    struct.pack_into('<II',anchor,248,zlib.crc32(anchor[:248]),0xa60c17ed)
    current=bytearray(original);current[:BOOT]=code+anchor;current[0xb0000:0xef000]=b'\x73'*0x3f000
    flash=c.create_string_buffer(bytes(current));family=hashlib.sha256(DOMAIN+code).digest()
    lib.restore_fault(0,0,0,0)
    lib.restore_io_fault(0xffffffff,0,0)
    return dict(original=original,table=table,live=live,flash=flash,family=family,seq=0)

def open_(lib,b,owner=42,epoch=77,kind=2):
    b['seq']=0
    return lib.restore_open(b['flash'],SIZE,c.byref(b['live']),b['family'],kind,owner,epoch)

def table_(lib,b):
    for off in range(0,8192,256):
        assert lib.restore_chunk(42,77,b['seq'],off,b['table'][off:off+256],256)==0;b['seq']+=1

def begin_(lib,b):
    rc=lib.restore_begin(42,77,b['seq']);b['seq']+=1;return rc

def page_(lib,b,address,data=None):
    data=b['original'][address:address+PAGE] if data is None else data
    for off in range(0,PAGE,256):
        rc=lib.restore_page(42,77,b['seq'],address,off,data[off:off+256],256);b['seq']+=1
        if rc:return rc
    rc=lib.restore_commit(42,77,b['seq'],address);b['seq']+=1;return rc

def prepared_(lib,b):
    assert open_(lib,b)==0;table_(lib,b);assert begin_(lib,b)==0
    for address in range(0,BOOT,PAGE):assert page_(lib,b,address)==0
    assert lib.restore_prepare(42,77,b['seq'])==0;b['seq']+=1

def test_only_live_common_family_anchor_admits_private_metadata(lib,backup):
    assert open_(lib,backup)==0
    assert lib.restore_erases()==lib.restore_writes()==0
    assert lib.restore_begin(42,77,0)<0

@pytest.mark.parametrize('damage',['uid','uicr','geometry','family','anchor','legacy'])
def test_unknown_or_changed_local_authority_never_enables_writes(lib,backup,damage):
    b=backup
    if damage=='uid':b['live'].uid[0]^=1
    elif damage=='uicr':b['live'].uicr_sha256[0]^=1
    elif damage=='geometry':b['live'].page_size=2048
    elif damage=='family':b['family']=b'\0'*32
    elif damage=='anchor':b['flash'][0xbffc]=b'\0'
    assert open_(lib,b,kind=1 if damage=='legacy' else 2)<0
    assert lib.restore_erases()==lib.restore_writes()==0

def test_owner_nonce_sequence_and_exact_contiguous_table_are_required(lib,backup):
    b=backup;assert open_(lib,b)==0
    assert lib.restore_chunk(43,77,0,0,b['table'][:256],256)<0
    assert lib.restore_chunk(42,78,0,0,b['table'][:256],256)<0
    table_(lib,b)
    assert lib.restore_chunk(42,77,0,0,b['table'][:256],256)<0
    assert begin_(lib,b)==0
    assert lib.restore_chunk(42,77,b['seq'],0,b['table'][:256],256)<0
    assert lib.restore_erases()==0

def test_original_boot_is_ram_only_and_scratch_is_never_a_page_target(lib,backup):
    b=backup;assert open_(lib,b)==0;table_(lib,b);assert begin_(lib,b)==0
    for address in range(0,BOOT,PAGE):assert page_(lib,b,address)==0
    assert lib.restore_erases()==lib.restore_writes()==0
    assert lib.restore_page(42,77,b['seq'],0xb0000,0,b'x'*256,256)<0

def test_real_page_mismatch_writes_then_readbacks_but_matching_page_is_skipped(lib,backup):
    b=backup;address=0xc000;b['flash'][address]=bytes([b['original'][address]^1])
    assert open_(lib,b)==0;table_(lib,b);assert begin_(lib,b)==0;assert page_(lib,b,address)==0
    assert lib.restore_erases()==1 and lib.restore_writes()==1024
    assert b['flash'].raw[address:address+PAGE]==b['original'][address:address+PAGE]
    assert page_(lib,b,address)==0;assert lib.restore_erases()==1

def test_protection_cancellation_after_erase_stops_before_first_program_word(lib,backup):
    b=backup;address=0xc000;b['flash'][address]=b'\x00'
    assert open_(lib,b)==0;table_(lib,b);assert begin_(lib,b)==0
    lib.restore_fault(0,0,0,1)
    assert page_(lib,b,address)<0
    assert lib.restore_erases()==1 and lib.restore_writes()==0

def test_hash_or_read_failure_is_not_mismatch_authority_to_erase(lib,backup):
    b=backup;assert open_(lib,b)==0;table_(lib,b);assert begin_(lib,b)==0
    lib.restore_fault(1,0,0,0)
    assert page_(lib,b,0xc000)<0;assert lib.restore_erases()==lib.restore_writes()==0

def test_actual_page_reader_error_never_becomes_permission_to_erase(lib,backup):
    b=backup;assert open_(lib,b)==0;table_(lib,b);assert begin_(lib,b)==0
    lib.restore_io_fault(0xc000,0,0)
    assert page_(lib,b,0xc000)<0
    assert lib.restore_erases()==lib.restore_writes()==lib.restore_finalizations()==0

@pytest.mark.parametrize('failure',['write','readback','accepted_table'])
def test_write_failure_readback_mismatch_or_changed_accepted_table_cannot_prepare(lib,backup,failure):
    b=backup;b['flash'][0xc000]=bytes([b['original'][0xc000]^1])
    assert open_(lib,b)==0;table_(lib,b);assert begin_(lib,b)==0
    if failure=='write':lib.restore_io_fault(0xffffffff,2,0)
    if failure=='readback':lib.restore_io_fault(0xffffffff,0,1)
    if failure=='accepted_table':lib.restore_corrupt_table()
    assert page_(lib,b,0xc000)<0
    if failure=='accepted_table':assert lib.restore_erases()==lib.restore_writes()==0
    else:assert lib.restore_erases()==1 and lib.restore_writes()>0
    assert lib.restore_prepare(42,77,b['seq'])<0 and lib.restore_finalizations()==0

def test_incomplete_and_mutated_table_never_reach_maintenance(lib,backup):
    b=backup;assert open_(lib,b)==0
    assert lib.restore_chunk(42,77,0,0,b['table'][:256],256)==0
    assert lib.restore_begin(42,77,1)<0
    assert open_(lib,b)==0;b['table']=bytes([b['table'][0]^1])+b['table'][1:]
    for off in range(0,8192,256):
        rc=lib.restore_chunk(42,77,b['seq'],off,b['table'][off:off+256],256);b['seq']+=1
    assert rc<0 and begin_(lib,b)<0
    assert lib.restore_erases()==lib.restore_writes()==0

def test_preparation_verifies_full_logical_flash_and_freezes_all_uploads(lib,backup):
    b=backup;prepared_(lib,b)
    assert lib.restore_page(42,77,b['seq'],0xc000,0,b'x'*256,256)<0;b['seq']+=1
    assert lib.restore_final_request(42,77,b['seq'])==0
    assert lib.restore_final_execute(42,77)==0
    assert lib.restore_finalizations()==1 and lib.restore_quiesces()==1

@pytest.mark.parametrize('damage',['outside','boot','uicr','shutdown','protection'])
def test_changed_prepared_state_or_failed_shutdown_never_enters_finalizer(lib,backup,damage):
    b=backup;prepared_(lib,b)
    if damage=='outside':b['flash'][0xf8000]=bytes([b['original'][0xf8000]^1])
    if damage=='boot':lib.restore_corrupt_boot()
    if damage=='uicr':lib.restore_live_fault()
    if damage=='shutdown':lib.restore_fault(0,0,1,0)
    if damage=='protection':lib.restore_fault(0,1,0,0)
    assert lib.restore_final_request(42,77,b['seq'])==0
    assert lib.restore_final_execute(42,77)<0 and lib.restore_finalizations()==0

def test_disconnect_cancels_old_epoch_and_requires_fresh_table_and_boot(lib,backup):
    b=backup;prepared_(lib,b);lib.restore_cancel(42)
    assert lib.restore_final_request(42,77,b['seq'])<0
    assert open_(lib,b,epoch=78)==0
    assert lib.restore_begin(42,78,0)<0 and lib.restore_erases()==0

def restore_image(lib,role=b'\x04',profile=2):
    from test_image_roles import fixture
    return fixture((None,lib.test_key,lib.test_keyhash),role=role,target=b'VIMAR30805'+bytes([profile]),vector_base=0xb0000)[0]

def test_bootstrap_requires_signed_restore_role_and_anchored_erased_scratch_then_copies_exact_bytes(lib,backup):
    b=backup;blob=restore_image(lib);before=b['flash'].raw[:BOOT]
    assert lib.restore_bootstrap_open(b['flash'],SIZE,c.byref(b['live']),b['family'],blob,len(blob))==0
    table_(lib,b);assert begin_(lib,b)==0
    assert lib.restore_bootstrap_copy(b['seq'])==0
    assert lib.restore_erases()==63 and lib.restore_loader_requests()==1
    assert b['flash'].raw[:BOOT]==before
    assert b['flash'].raw[0xb0000:0xb0000+len(blob)]==blob
    assert b['flash'].raw[0xb0000+len(blob):0xef000]==b'\xff'*(0x3f000-len(blob))

@pytest.mark.parametrize('failure',['tamper','protection','write','quiesce'])
def test_bootstrap_changed_blob_failed_copy_or_shutdown_never_requests_loader(lib,backup,failure):
    b=backup;blob=c.create_string_buffer(restore_image(lib))
    assert lib.restore_bootstrap_open(b['flash'],SIZE,c.byref(b['live']),b['family'],blob,len(blob)-1)==0
    table_(lib,b);assert begin_(lib,b)==0
    if failure=='tamper':blob[40]=bytes([blob.raw[40]^1])
    if failure=='protection':lib.restore_fault(0,0,0,1)
    if failure=='write':lib.restore_io_fault(0xffffffff,2,0)
    if failure=='quiesce':lib.restore_fault(0,0,1,0)
    assert lib.restore_bootstrap_copy(b['seq'])<0
    assert lib.restore_loader_requests()==0
    if failure=='tamper':assert lib.restore_erases()==lib.restore_writes()==0
    if failure=='protection':assert lib.restore_erases()==1 and lib.restore_writes()==0

@pytest.mark.parametrize('damage',['main','migration','recovery','diagnostic','profile','signature'])
def test_bootstrap_rejects_other_valid_roles_or_bad_signature_before_maintenance_or_erase(lib,backup,damage):
    b=backup;roles={'main':b'\x01','migration':b'\x03','recovery':b'\x02','diagnostic':b'\x05'}
    blob=restore_image(lib,roles.get(damage,b'\x04'),1 if damage=='profile' else 2)
    if damage=='signature':blob=blob[:-1]+bytes([blob[-1]^1])
    assert lib.restore_bootstrap_open(b['flash'],SIZE,c.byref(b['live']),b['family'],blob,len(blob))==0
    table_(lib,b);assert begin_(lib,b)<0
    assert lib.restore_erases()==lib.restore_writes()==lib.restore_loader_requests()==0

def test_role_uid_and_boot_nonce_separate_ephemeral_bonds_without_a_mac_registry(lib):
    nonce=bytes(range(16));out=c.create_string_buffer(6)
    assert lib.restore_radio(0x11223344,0x55667788,nonce,4,out)==0
    expected=bytearray(hashlib.sha256(b'VIMAR30805-STOCK-RESTORE-BLE-V1\0'+b'\x04'+struct.pack('<II',0x11223344,0x55667788)+nonce).digest()[:6]);expected[5]|=0xc0
    assert out.raw==expected
    results={out.raw}
    for uid0,role,random in [(0x11223345,4,nonce),(0x11223344,3,nonce),(0x11223344,4,b'\x80'+nonce[1:])]:
        assert lib.restore_radio(uid0,0x55667788,random,role,out)==0;results.add(out.raw);assert out.raw[5]&0xc0==0xc0
    assert len(results)==4

def command(op,seq,address=0,arg=0,data=b'',epoch=77):
    return struct.pack('<BBHIIIIHH',2,op,0,epoch,seq,address,arg,len(data),0)+data

def test_wire_protocol_bounds_every_field_and_reports_server_nonce_and_accepted_identity(lib,backup):
    b=backup;assert open_(lib,b)==0
    for bad in [b'',command(2,0)+b'x',command(99,0),command(2,0,address=4),command(1,0,data=b'x'*193)]:
        assert lib.restore_protocol(bad,len(bad))<0
    seq=0
    for off in range(0,8192,192):
        data=b['table'][off:off+192];frame=command(1,seq,arg=off,data=data)
        assert lib.restore_protocol(frame,len(frame))==0;seq+=1
    assert lib.restore_protocol(command(2,seq),24)==0
    out=c.create_string_buffer(128);assert lib.restore_reply(out)==0
    assert out.raw[0]==2 and struct.unpack_from('<I',out.raw,8)[0]==77
    assert struct.unpack_from('<II',out.raw,36)==tuple(b['live'].uid)
    assert out.raw[48:80]==b['family']
    assert lib.restore_erases()==lib.restore_writes()==0
