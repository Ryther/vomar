"""Portable recovery migration with actual signed bundle and RAM flash faults."""
from local_inputs import local_input, sdk_root
import ctypes
import hashlib
import subprocess
from pathlib import Path
import pytest
from test_ota_image import lib as image_lib, Info
ROOT=Path(__file__).resolve().parents[3]
LOW,HIGH,PAGE=0xb0000,0xf0000,4096
UID=(0xe0d9cce1,0x022edd22)
READ_UID=ctypes.CFUNCTYPE(ctypes.c_int,ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32))
HASH=ctypes.CFUNCTYPE(ctypes.c_int,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p)
VERIFY=ctypes.CFUNCTYPE(ctypes.c_int,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t)
READ=ctypes.CFUNCTYPE(ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_size_t)
ERASE=ctypes.CFUNCTYPE(ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_size_t)
class Bundle(ctypes.Structure):
    _fields_=[('uid',ctypes.c_uint32*2),('data',ctypes.c_void_p),('size',ctypes.c_size_t),('sha256',ctypes.c_uint8*32)]
class Io(ctypes.Structure):
    _fields_=[('ctx',ctypes.c_void_p),('read_uid',READ_UID),('sha256',HASH),('verify_image',VERIFY),('read',READ),('erase',ERASE),('write',READ)]
@pytest.fixture(scope='session')
def migration_lib(tmp_path_factory):
    so=tmp_path_factory.mktemp('migration')/'migration.so'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(ROOT/'firmware/ota_migration/src/migration_copy.c'),'-o',str(so)],check=True)
    lib=ctypes.CDLL(str(so));lib.migration_copy_run.argtypes=[ctypes.POINTER(Bundle),ctypes.POINTER(Io)]
    return lib
@pytest.fixture(scope='session')
def recovery():
    return local_input(ROOT/'experiments/zigbee-ota-20261020/recovery-0.7.0.signed.bin').read_bytes()
def invoke(migration_lib,image_lib,recovery,memory=None,*,wrong_uid=False,bad_hash=False,signature_error=0,fail_erase=None,fail_write=None,corrupt_readback=False):
    if memory is None:memory=ctypes.create_string_buffer(b'\xa5'*0x100000)
    source=ctypes.create_string_buffer(recovery)
    bundle=Bundle((ctypes.c_uint32*2)(*UID),ctypes.addressof(source),len(recovery));bundle.sha256[:]=hashlib.sha256(recovery).digest()
    if bad_hash:bundle.sha256[0]^=1
    mutations=[];verify_calls=[]
    @READ_UID
    def read_uid(ctx,out):out[0]=UID[0]^(1 if wrong_uid else 0);out[1]=UID[1];return 0
    @HASH
    def sha(ctx,data,size,out):ctypes.memmove(out,hashlib.sha256(ctypes.string_at(data,size)).digest(),32);return 0
    @VERIFY
    def verify(ctx,data,size):
        verify_calls.append(size)
        if signature_error:return signature_error
        result=Info();image_lib.ota_image_verify_primary.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(Info)]
        rc=image_lib.ota_image_verify_primary(data,size,ctypes.byref(result))
        return rc if rc else (0 if result.output_size==size else -74)
    @READ
    def read(ctx,address,out,size):
        assert LOW<=address<=HIGH-size
        ctypes.memmove(out,ctypes.addressof(memory)+address,size);return 0
    @ERASE
    def erase(ctx,address,size):
        assert address%PAGE==0 and size==PAGE and LOW<=address<=HIGH-PAGE and verify_calls
        mutations.append(('erase',address))
        if address==fail_erase:return -5
        ctypes.memset(ctypes.addressof(memory)+address,255,size);return 0
    @READ
    def write(ctx,address,data,size):
        assert address%PAGE==0 and size==PAGE and LOW<=address<=HIGH-PAGE
        mutations.append(('write',address));ctypes.memmove(ctypes.addressof(memory)+address,data,size//2 if address==fail_write else size)
        if address==fail_write:return -5
        if corrupt_readback:memory[address]=bytes([memory[address][0]^1])
        return 0
    io=Io(None,read_uid,sha,verify,read,erase,write)
    rc=migration_lib.migration_copy_run(ctypes.byref(bundle),ctypes.byref(io))
    return rc,memory,mutations

def assert_complete(memory,recovery):
    assert bytes(memory[LOW:LOW+len(recovery)])==recovery
    assert bytes(memory[LOW+len(recovery):HIGH])==b'\xff'*(HIGH-LOW-len(recovery))
    assert bytes(memory[:LOW])==b'\xa5'*LOW
    assert bytes(memory[HIGH:0x100000])==b'\xa5'*(0x100000-HIGH)

def test_authenticated_copy_and_idempotence(migration_lib,image_lib,recovery):
    rc,memory,mutations=invoke(migration_lib,image_lib,recovery)
    assert rc==0 and len(mutations)==128
    assert_complete(memory,recovery)
    rc,_,mutations=invoke(migration_lib,image_lib,recovery,memory)
    assert rc==0 and mutations==[]
@pytest.mark.parametrize('fault',[{'wrong_uid':True},{'bad_hash':True},{'signature_error':-13},{'signature_error':-5}])
def test_preflight_failure_never_mutates(migration_lib,image_lib,recovery,fault):
    rc,_,mutations=invoke(migration_lib,image_lib,recovery,**fault)
    assert rc<0 and mutations==[]
def test_corrupt_signed_bundle_rejected(migration_lib,image_lib,recovery):
    corrupted=recovery[:700]+bytes([recovery[700]^1])+recovery[701:]
    rc,_,mutations=invoke(migration_lib,image_lib,corrupted)
    assert rc<0 and mutations==[]
@pytest.mark.parametrize('operation',['fail_erase','fail_write'])
def test_interruption_at_every_recovery_page_then_resume(migration_lib,image_lib,recovery,operation):
    for page in range(LOW,HIGH,PAGE):
        rc,memory,_=invoke(migration_lib,image_lib,recovery,**{operation:page})
        assert rc==-5
        rc,memory,mutations=invoke(migration_lib,image_lib,recovery,memory)
        assert rc==0
        assert all(address>=page for _,address in mutations)
        assert_complete(memory,recovery)
def test_readback_error_stops_copy(migration_lib,image_lib,recovery):
    rc,_,mutations=invoke(migration_lib,image_lib,recovery,corrupt_readback=True)
    assert rc<0 and mutations==[('erase',LOW),('write',LOW)]
def test_oversize_bundle_rejected(migration_lib,image_lib):
    rc,_,mutations=invoke(migration_lib,image_lib,b'X'*(HIGH-LOW+1))
    assert rc<0 and mutations==[]
