"""Independent wire decoding for the bounded read-only Zigbee pair contract."""
import base64
import ctypes
from pathlib import Path
import struct
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[3]

@pytest.fixture(scope='module')
def codec(tmp_path_factory):
    directory=tmp_path_factory.mktemp('ota-runtime-codec');library=directory/'codec.so'
    subprocess.run(['cc','-shared','-fPIC','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=undefined',
        '-I',str(ROOT/'firmware/src'),str(ROOT/'firmware/src/ota_runtime_contract.c'),'-o',str(library)],check=True)
    function=ctypes.CDLL(str(library)).ota_runtime_contract_encode
    function.argtypes=[ctypes.c_uint32,ctypes.c_uint32,ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p]
    function.restype=ctypes.c_int
    return function

@pytest.mark.parametrize('sample,boot',[(0,0),(1,2),(0xffffffff,0xffffffff)])
@pytest.mark.parametrize('ready',[False,True])
def test_exact_canonical_wire_and_single_frame_bound(codec,sample,boot,ready):
    digest=bytes(range(32));source=ctypes.create_string_buffer(digest);out=ctypes.create_string_buffer(62)
    assert codec(sample,boot,ready,source,out)==0
    assert out.raw[0]==43
    binary=out.raw[1:44]
    assert binary==bytes([1,2,int(ready)])+struct.pack('<II',sample,boot)+(digest if ready else bytes(32))
    text=b'v1:'+base64.urlsafe_b64encode(binary).rstrip(b'=');assert len(text)==61 and b'=' not in text
    # Conservative SDK ZB_ZCL_HI_MAX_PAYLOAD_SIZE is66; standalone READ is51.
    assert 3+4+1+len(binary)==51<=66

def test_rejects_missing_verified_digest_and_handles_output_alias(codec):
    out=ctypes.create_string_buffer(b'x'*62,62)
    assert codec(0,0,True,None,out)<0 and out.raw[0]==0
    assert codec(0,0,False,None,out)==0
    digest=bytes(range(32));out=ctypes.create_string_buffer(digest+b'\0'*30,62)
    assert codec(3,4,True,out,out)==0
    binary=out.raw[1:44];assert binary[11:]==digest
