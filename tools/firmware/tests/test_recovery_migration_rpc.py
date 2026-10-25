"""Real SDK zcbor decoder and actual8042 handler, with explicit gate-call IO."""
from local_inputs import local_input, sdk_root
import ctypes as c
from pathlib import Path
import subprocess

import cbor2
import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope='module')
def rpc(tmp_path_factory):
    base = tmp_path_factory.mktemp('migration_rpc')
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
#include "recovery_migration.h"
#include <zephyr/mgmt/mcumgr/mgmt/mgmt.h>
#include <zephyr/mgmt/mcumgr/smp/smp.h>
#include <assert.h>
#include <string.h>
static struct mgmt_group*registered;
static unsigned calls;
static int request_error;
static unsigned char observed[32];
void mgmt_register_group(struct mgmt_group*g){registered=g;}
int recovery_exit_zephyr_migration_request(const uint8_t hash[32])
{calls++;memcpy(observed,hash,32);return request_error;}
unsigned request_calls(void){return calls;}
const unsigned char*request_hash(void){return observed;}
int execute(const unsigned char*request,size_t size,unsigned char*response,size_t capacity,int error)
{
 calls=0;request_error=error;memset(observed,0,sizeof(observed));
 recovery_migration_register();assert(registered&&registered->mg_group_id==0x8042);
 assert(registered->mg_handlers_count==1&&!registered->mg_handlers[0].mh_read&&registered->mg_handlers[0].mh_write);
 ZCBOR_STATE_D(dec,3,request,size,1,0);
 ZCBOR_STATE_E(enc,3,response,capacity,1);
 struct reader reader={.zs=dec};struct writer writer={.zs=enc};
 struct smp_streamer stream={.reader=&reader,.writer=&writer};
 if(!zcbor_map_start_encode(enc,1))return -107;
 int rc=registered->mg_handlers[0].mh_write(&stream);
 if(rc)return -rc;
 if(!zcbor_map_end_encode(enc,1))return -107;
 return (int)(enc->payload-response);
}
''')
    zcbor = local_input(sdk_root()/'modules/lib/zcbor')
    library = base / 'rpc.so'
    subprocess.run(['cc', '-shared', '-fPIC', '-std=c11', '-Wall', '-Wextra', '-Werror',
        '-Wno-unused-but-set-variable',  # SDK zcbor_decode.c without verbose assertions.
        '-fsanitize=undefined', '-fno-sanitize-recover=all', '-I' + str(base),
        '-I' + str(zcbor / 'include'), '-I' + str(ROOT / 'firmware/recovery/src'),
        str(harness), str(ROOT / 'firmware/recovery/src/recovery_migration.c'),
        str(ROOT / 'firmware/recovery/src/recovery_migration_zephyr.c'),
        str(zcbor / 'src/zcbor_common.c'), str(zcbor / 'src/zcbor_decode.c'),
        str(zcbor / 'src/zcbor_encode.c'), '-o', str(library)], check=True, capture_output=True)
    lib = c.CDLL(str(library))
    lib.execute.argtypes = [c.c_void_p, c.c_size_t, c.c_void_p, c.c_size_t, c.c_int]
    lib.request_hash.restype = c.POINTER(c.c_uint8)
    return lib


def execute(rpc, payload, capacity=128, error=0):
    output = c.create_string_buffer(capacity)
    rc = rpc.execute(payload, len(payload), output, capacity, error)
    return rc, output.raw[:max(0, rc)]


def test_only_write0_has_exact_hash_request_and_ack(rpc):
    digest = bytes(range(32))
    rc, response = execute(rpc, cbor2.dumps({'hash': digest}))
    assert rc > 0 and cbor2.loads(response) == {'accepted': True}
    assert rpc.request_calls() == 1 and bytes(rpc.request_hash()[:32]) == digest


@pytest.mark.parametrize('payload', [
    b'', b'\xa0', b'\xf6', b'\xa1\x64hash\xf5',
    cbor2.dumps({'hash': bytes(31)}), cbor2.dumps({'hash': bytes(33)}),
    cbor2.dumps({'hash': '00' * 32}), cbor2.dumps({'other': bytes(32)}),
    cbor2.dumps({'hash': bytes(32), 'extra': 0}),
    b'\xa2\x64hash\x58\x20' + bytes(32) + b'\x64hash\x58\x20' + bytes(32),
    cbor2.dumps({'hash': bytes(32)}) + b'\xa0',
    cbor2.dumps({'hash': bytes(32)})[:-1],
])
def test_malformed_duplicate_extra_and_trailing_payload_never_reserves_transition(rpc, payload):
    rc, _ = execute(rpc, payload)
    assert rc == -3 and rpc.request_calls() == 0


def test_encoding_failure_never_reserves_transition(rpc):
    rc, _ = execute(rpc, cbor2.dumps({'hash': bytes(32)}), capacity=2)
    assert rc < 0 and rpc.request_calls() == 0


@pytest.mark.parametrize('error,expected', [(-16, -10), (-13, -11), (-5, -11)])
def test_policy_failure_is_not_success_or_unsupported(rpc, error, expected):
    rc, _ = execute(rpc, cbor2.dumps({'hash': bytes(32)}), error=error)
    assert rc == expected and rpc.request_calls() == 1
