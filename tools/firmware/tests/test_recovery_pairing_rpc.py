"""Actual pairing RPC with the pinned SDK CBOR codec; synthetic IO only."""
from local_inputs import local_input, sdk_root
import ctypes as c
from pathlib import Path
import subprocess
import cbor2
import pytest
ROOT=Path(__file__).resolve().parents[3]

@pytest.fixture(scope='module')
def rpc(tmp_path_factory):
    base = tmp_path_factory.mktemp('pairing_rpc')
    headers = {
        'zephyr/mgmt/mcumgr/mgmt/mgmt.h': '''#include <stddef.h>
#include <stdint.h>
struct smp_streamer;
struct mgmt_handler {int(*mh_read)(struct smp_streamer*);int(*mh_write)(struct smp_streamer*);};
struct mgmt_group {const struct mgmt_handler*mg_handlers;size_t mg_handlers_count;uint16_t mg_group_id;};
void mgmt_register_group(struct mgmt_group*);
#define MGMT_ERR_EOK 0
#define MGMT_ERR_EINVAL 3
#define MGMT_ERR_EMSGSIZE 7
#define MGMT_ERR_EBUSY 10
#define MGMT_ERR_EACCESSDENIED 11
''',
        'zephyr/mgmt/mcumgr/smp/smp.h': '''#include <zcbor_encode.h>
struct reader {zcbor_state_t*zs;};struct writer {zcbor_state_t*zs;};
struct smp_streamer {struct reader*reader;struct writer*writer;};
''',
    }
    for name, source in headers.items():
        path = base / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(source)
    harness = base / 'rpc.c'
    harness.write_text(r'''
#include "recovery_pairing.h"
#include <zcbor_decode.h>
#include <zephyr/mgmt/mcumgr/mgmt/mgmt.h>
#include <zephyr/mgmt/mcumgr/smp/smp.h>
#include <assert.h>
#include <string.h>
static struct mgmt_group*registered;
static unsigned calls;
static int request_error;

void mgmt_register_group(struct mgmt_group*g){registered=g;}
int recovery_exit_zephyr_pairing_capable(void){return request_error;}
int recovery_exit_zephyr_pairing_request(void)
{calls++;return request_error;}
unsigned request_calls(void){return calls;}

int execute(const unsigned char*request,size_t size,unsigned char*response,size_t capacity,int error,int write)
{
 calls=0;request_error=error;
 recovery_pairing_register();assert(registered&&registered->mg_group_id==0x8043);
 assert(registered->mg_handlers_count==1&&registered->mg_handlers[0].mh_read&&registered->mg_handlers[0].mh_write);
 ZCBOR_STATE_D(dec,3,request,size,1,0);
 ZCBOR_STATE_E(enc,3,response,capacity,1);
 struct reader reader={.zs=dec};struct writer writer={.zs=enc};
 struct smp_streamer stream={.reader=&reader,.writer=&writer};
 if(!zcbor_map_start_encode(enc,3))return -107;
 int rc=write?registered->mg_handlers[0].mh_write(&stream):registered->mg_handlers[0].mh_read(&stream);
 if(rc)return -rc;
 if(!zcbor_map_end_encode(enc,3))return -107;
 return (int)(enc->payload-response);
}
''')
    zcbor = local_input(sdk_root()/'modules/lib/zcbor')
    library = base / 'rpc.so'
    subprocess.run(['cc', '-shared', '-fPIC', '-std=c11', '-Wall', '-Wextra', '-Werror',
        '-Wno-unused-but-set-variable',  # SDK zcbor_decode.c without verbose assertions.
        '-fsanitize=undefined', '-fno-sanitize-recover=all', '-I' + str(base),
        '-I' + str(zcbor / 'include'), '-I' + str(ROOT / 'firmware/recovery/src'),
        str(harness),
        str(ROOT / 'firmware/recovery/src/recovery_pairing_zephyr.c'),
        str(zcbor / 'src/zcbor_common.c'), str(zcbor / 'src/zcbor_decode.c'),
        str(zcbor / 'src/zcbor_encode.c'), '-o', str(library)], check=True)
    lib = c.CDLL(str(library))
    lib.execute.argtypes = [c.c_void_p, c.c_size_t, c.c_void_p, c.c_size_t, c.c_int,c.c_int]
    return lib


def execute(rpc, payload, capacity=128, error=0,write=1):
    output = c.create_string_buffer(capacity)
    rc = rpc.execute(payload, len(payload), output, capacity, error,write)
    return rc, output.raw[:max(0, rc)]



def test_pairing_capabilities_are_read_only(rpc):
    rc,response=execute(rpc,cbor2.dumps({}),write=0)
    assert rc>0 and cbor2.loads(response)=={'protocol':1,'duration':120,'forget':True}
    assert rpc.request_calls()==0


def test_pairing_request_is_explicit_exact_and_acknowledged(rpc):
    rc,response=execute(rpc,cbor2.dumps({'duration':120,'forget':True}))
    assert rc>0 and cbor2.loads(response)=={'accepted':True}
    assert rpc.request_calls()==1


@pytest.mark.parametrize('value',[{}, {'duration':119,'forget':True},{'duration':120,'forget':False},
 {'duration':120,'forget':1},{'duration':True,'forget':True},{'duration':120,'forget':True,'extra':0}])
def test_pairing_rejects_missing_wrong_or_extra_fields(rpc,value):
    assert execute(rpc,cbor2.dumps(value))[0]==-3
    assert rpc.request_calls()==0


def test_pairing_rejects_trailing_payload_and_output_exhaustion(rpc):
    request=cbor2.dumps({'duration':120,'forget':True})
    assert execute(rpc,request+b'\x00')[0]==-3
    assert rpc.request_calls()==0
    assert execute(rpc,request,capacity=2)[0]<0
    assert rpc.request_calls()==0
    assert execute(rpc,request,error=-16)[0]==-10
