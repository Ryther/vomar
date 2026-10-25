"""Real pinned SDK zcbor reporting format; no registered SMP handler."""
from local_inputs import local_input, sdk_root
import ctypes as c
from pathlib import Path
import subprocess
import cbor2
import pytest
from test_loader_runtime import Snapshot
ROOT=Path(__file__).resolve().parents[3]

@pytest.fixture(scope='module')
def codec(tmp_path_factory):
 d=tmp_path_factory.mktemp('runtime_cbor');source=d/'codec.c'
 source.write_text(r'''
#include "loader_runtime_cbor.h"
int encode(const struct loader_runtime_identity*i,unsigned char*out,size_t size){
 ZCBOR_STATE_E(state,4,out,size,1);
 if(!zcbor_map_start_encode(state,5)||!loader_runtime_identity_encode(state,i)||!zcbor_map_end_encode(state,5))return-1;
 return (int)(state->payload-out);
}
''')
 sdk=local_input(sdk_root()/'modules/lib/zcbor');library=d/'codec.so'
 subprocess.run(['cc','-shared','-fPIC','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=undefined',
  '-I'+str(ROOT/'firmware/loader_contract'),'-I'+str(sdk/'include'),str(source),str(ROOT/'firmware/loader_contract/loader_runtime_cbor.c'),
  str(sdk/'src/zcbor_common.c'),str(sdk/'src/zcbor_encode.c'),'-o',str(library)],check=True,capture_output=True)
 lib=c.CDLL(str(library));lib.encode.argtypes=[c.POINTER(Snapshot),c.c_void_p,c.c_size_t];return lib

@pytest.mark.parametrize('kind',[1,2])
def test_exact_typed_identity_and_atomic_input_alias(codec,kind):
 storage=c.create_string_buffer(512);identity=Snapshot.from_buffer(storage,8);identity.uid[:]=[0x12345678,0xffffffff];identity.kind=kind;identity.digest[:]=bytes(range(32));identity.anchor_sha256[:]=b'\xa5'*32 if kind==2 else bytes(32)
 expected=dict(protocol=2,model='VIMAR30805',layout=2,uid=[0x12345678,0xffffffff],loader=dict(kind='legacy-full48k-sha256' if kind==1 else 'common-code44k-anchor-v1',digest=bytes(range(32))))
 if kind==2:expected['loader']['anchor_sha256']=b'\xa5'*32
 n=codec.encode(c.byref(identity),storage,512);assert n>0 and cbor2.loads(storage.raw[:n])==expected
 assert n+8<512

@pytest.mark.parametrize('kind',[0,3,99])
def test_unknown_type_never_emits_identity(codec,kind):
 identity=Snapshot();identity.kind=kind;out=c.create_string_buffer(512);assert codec.encode(c.byref(identity),out,512)<0

def test_legacy_cannot_smuggle_anchor_measurement_and_small_buffer_fails(codec):
 identity=Snapshot();identity.kind=1;identity.anchor_sha256[0]=1;out=c.create_string_buffer(512)
 assert codec.encode(c.byref(identity),out,512)<0
 identity.kind=2;assert codec.encode(c.byref(identity),out,5)<0
