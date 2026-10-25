"""Actual identity-group handler: default-off READ1 and unchanged READ0."""
from local_inputs import local_input, sdk_root
import ctypes as c
from pathlib import Path
import subprocess
import cbor2,pytest
ROOT=Path(__file__).resolve().parents[3]

@pytest.fixture(params=[False,True])
def identity(tmp_path,request):
 d=tmp_path;enabled=request.param
 headers={
 'hal/nrf_ficr.h':'#include <stdint.h>\n#define NRF_FICR ((void*)0)\nstatic inline uint32_t nrf_ficr_deviceid_get(void*p,unsigned i){(void)p;return i?2:1;}\n',
 'zephyr/drivers/flash.h':'''#include <stdint.h>
#include <stddef.h>
#define ARG_UNUSED(x) (void)(x)
struct device {int n;};extern const struct device fake_device;
#define DEVICE_DT_GET(x) (&fake_device)
#define DT_CHOSEN(x) 0
static inline int device_is_ready(const struct device*d){(void)d;return 1;}
int flash_read(const struct device*,uint32_t,void*,size_t);
''',
 'zephyr/mgmt/mcumgr/mgmt/mgmt.h':'''#include <stddef.h>
#include <stdint.h>
struct smp_streamer;
struct mgmt_handler{int(*mh_read)(struct smp_streamer*);int(*mh_write)(struct smp_streamer*);};
struct mgmt_group{const struct mgmt_handler*mg_handlers;size_t mg_handlers_count;uint16_t mg_group_id;};
void mgmt_register_group(struct mgmt_group*);
#define MGMT_ERR_EOK 0
#define MGMT_ERR_EUNKNOWN 1
#define MGMT_ERR_EINVAL 3
#define MGMT_ERR_EMSGSIZE 7
#define MGMT_ERR_ENOTSUP 8
#define MGMT_ERR_EACCESSDENIED 11
''',
 'zephyr/mgmt/mcumgr/smp/smp.h':'''#include <zcbor_encode.h>
struct reader{zcbor_state_t*zs;};struct writer{zcbor_state_t*zs;};struct smp_streamer{struct reader*reader;struct writer*writer;};
''',
 'zephyr/bluetooth/gatt.h':'''#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>
struct bt_conn;struct bt_gatt_attr;struct bt_uuid_128{int uuid;};
#define BT_UUID_INIT_128(...) {0}
#define BT_UUID_128_ENCODE(...) 0
#define BT_GATT_SERVICE_DEFINE(...)
#define BT_GATT_PRIMARY_SERVICE(...) 0
#define BT_GATT_CHARACTERISTIC(...) 0
#define BT_GATT_CHRC_READ 1
#define BT_GATT_PERM_READ_AUTHEN 2
static inline ssize_t bt_gatt_attr_read(struct bt_conn*c,const struct bt_gatt_attr*a,void*b,uint16_t n,uint16_t o,const void*v,size_t s){(void)c;(void)a;(void)b;(void)n;(void)o;(void)v;return(ssize_t)s;}
'''}
 for name,value in headers.items():p=d/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value)
 source=d/'handler.c';source.write_text(r'''
#include "recovery_identity_zephyr.c"
#include "loader_runtime_zephyr.h"
#include <zcbor_decode.h>
#include <assert.h>
#include <string.h>
#include <errno.h>
const struct device fake_device={0};static struct mgmt_group*registered_group;static unsigned legacy_calls,new_calls;static int snapshot_error;
void mgmt_register_group(struct mgmt_group*g){registered_group=g;}
int flash_read(const struct device*d,uint32_t a,void*p,size_t n){(void)d;(void)a;memset(p,0,n);return 0;}
int ota_image_reader_sha256(const struct ota_reader*r,uint32_t off,size_t n,uint8_t out[32]){assert(r->size==0xc000&&off==0&&n==0xc000);legacy_calls++;memset(out,0x11,32);return 0;}
int loader_runtime_zephyr_snapshot(struct loader_runtime_identity*out){new_calls++;if(snapshot_error)return snapshot_error;memset(out,0,sizeof(*out));out->uid[0]=1;out->uid[1]=2;out->kind=LOADER_CONTRACT_COMMON_CODE44K_ANCHOR_V1;memset(out->digest,0x22,32);memset(out->anchor_sha256,0x33,32);return 0;}
unsigned old_calls(void){return legacy_calls;}unsigned typed_calls(void){return new_calls;}
int invoke(unsigned id,const uint8_t*request,size_t size,uint8_t*response,size_t capacity,int error){
 legacy_calls=new_calls=0;snapshot_error=error;recovery_identity_register();assert(registered_group->mg_group_id==0x8040);
 if(id>=registered_group->mg_handlers_count)return-MGMT_ERR_ENOTSUP;
 assert(registered_group->mg_handlers[id].mh_read&&!registered_group->mg_handlers[id].mh_write);
 ZCBOR_STATE_D(dec,4,request,size,1,0);ZCBOR_STATE_E(enc,4,response,capacity,1);
 struct reader reader={dec};struct writer writer={enc};struct smp_streamer stream={&reader,&writer};
 if(!zcbor_map_start_encode(enc,5))return-7;
 int rc=registered_group->mg_handlers[id].mh_read(&stream);if(rc)return-rc;
 if(!zcbor_map_end_encode(enc,5))return-7;return(int)(enc->payload-response);
}
''')
 sdk=local_input(sdk_root()/'modules/lib/zcbor');lib=d/'identity.so'
 flags=['-DCONFIG_VIMAR_LOADER_RUNTIME_V2=1','-DCONFIG_SOC_NRF52840=1','-DCONFIG_VIMAR_OTA_SPLIT_STAGING=1','-DCONFIG_PSA_WANT_ALG_SHA_256=1','-DCONFIG_VIMAR_P031_PROTECTION=1','-DCONFIG_MAIN_STACK_SIZE=12288','-DCONFIG_MCUMGR_TRANSPORT_BT=1','-DCONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN=1','-DCONFIG_MCUMGR_TRANSPORT_WORKQUEUE_STACK_SIZE=8192','-DVIMAR_LOADER_CONTRACT_BINDINGS_HEADER="unused.h"'] if enabled else []
 subprocess.run(['cc','-shared','-fPIC','-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-const-variable','-Wno-unused-but-set-variable','-Wno-misleading-indentation','-fsanitize=undefined',*flags,
 '-I'+str(d),'-I'+str(ROOT/'firmware/recovery/src'),'-I'+str(ROOT/'firmware/ota'),'-I'+str(ROOT/'firmware/loader_contract'),'-I'+str(sdk/'include'),str(source),str(ROOT/'firmware/recovery/src/recovery_identity.c'),str(ROOT/'firmware/loader_contract/loader_runtime_cbor.c'),str(sdk/'src/zcbor_common.c'),str(sdk/'src/zcbor_decode.c'),str(sdk/'src/zcbor_encode.c'),'-o',str(lib)],check=True,capture_output=True)
 module=c.CDLL(str(lib));module.invoke.argtypes=[c.c_uint,c.c_void_p,c.c_size_t,c.c_void_p,c.c_size_t,c.c_int];return module,enabled

def invoke(lib,id,payload=b'\xa0',error=0):
 out=c.create_string_buffer(512);n=lib.invoke(id,payload,len(payload),out,512,error);return n,cbor2.loads(out.raw[:n]) if n>0 else None

def test_read0_stays_protocol1_and_read1_requires_explicit_optin(identity):
 lib,enabled=identity;n,old=invoke(lib,0)
 assert n>0 and old==dict(protocol=1,model='VIMAR30805',layout=2,uid=[1,2],loader_sha256=b'\x11'*32)
 assert lib.old_calls()==1 and lib.typed_calls()==0
 n,new=invoke(lib,1)
 if enabled:
  assert n>0 and new==dict(protocol=2,model='VIMAR30805',layout=2,uid=[1,2],loader=dict(kind='common-code44k-anchor-v1',digest=b'\x22'*32,anchor_sha256=b'\x33'*32))
  assert lib.old_calls()==0 and lib.typed_calls()==1
 else:assert n==-8 and lib.typed_calls()==0

@pytest.mark.parametrize('payload',[b'',b'\x01',cbor2.dumps({'anchor':bytes(4096)}),b'\xa0\xa0'],ids=['empty','scalar','host-anchor','trailing'])
def test_read1_never_accepts_host_identity_fields_or_malformed_read_payload(identity,payload):
 lib,enabled=identity;n,_=invoke(lib,1,payload)
 assert n==(-3 if enabled else -8) and lib.typed_calls()==0 and lib.old_calls()==0

def test_unknown_or_mismatched_family_never_downgrades_to_read0(identity):
 lib,enabled=identity;n,_=invoke(lib,1,error=-13)
 assert n==(-11 if enabled else -8) and lib.old_calls()==0
