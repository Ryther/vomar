"""Actual Zephyr provider uses only fixed local flash/FICR/UICR + compiled authority."""
import ctypes as c,errno,hashlib,subprocess
from pathlib import Path
import pytest
from test_loader_contract import CODE,DOMAIN,fixture
from test_loader_runtime import Snapshot
from test_image_roles import Info
ROOT=Path(__file__).resolve().parents[3]
@pytest.fixture(scope='module')
def provider(tmp_path_factory):
 d=tmp_path_factory.mktemp('runtime_provider');family=hashlib.sha256(DOMAIN+CODE).digest()
 headers={
 'hal/nrf_ficr.h':'''#include <stdint.h>
struct ficr {struct {uint32_t PART,VARIANT,RAM;}INFO;uint32_t uid[2],page_size,page_count;};extern struct ficr local_ficr;
#define NRF_FICR (&local_ficr)
static inline uint32_t nrf_ficr_deviceid_get(struct ficr*p,unsigned i){return p->uid[i];}
static inline uint32_t nrf_ficr_codepagesize_get(struct ficr*p){return p->page_size;}
static inline uint32_t nrf_ficr_codesize_get(struct ficr*p){return p->page_count;}
''',
 'zephyr/drivers/flash.h':'''#include <stddef.h>
#include <stdint.h>
struct device {int ready;};extern struct device fake_flash;
#define DEVICE_DT_GET(x) (&fake_flash)
#define DT_CHOSEN(x) 0
static inline int device_is_ready(const struct device*p){return p->ready;}
int flash_read(const struct device*,uint32_t,void*,size_t);
''',
 'psa/crypto.h':'''#include <openssl/evp.h>
#include <stddef.h>
#include <stdint.h>
#define PSA_SUCCESS 0
#define PSA_ALG_SHA_256 1
typedef struct {EVP_MD_CTX*ctx;} psa_hash_operation_t;
static inline psa_hash_operation_t psa_hash_operation_init(void){return(psa_hash_operation_t){0};}
static inline int psa_crypto_init(void){return 0;}
static inline int psa_hash_setup(psa_hash_operation_t*p,int algorithm){(void)algorithm;p->ctx=EVP_MD_CTX_new();return p->ctx&&EVP_DigestInit_ex(p->ctx,EVP_sha256(),NULL)==1?0:-1;}
static inline int psa_hash_update(psa_hash_operation_t*p,const uint8_t*d,size_t n){return EVP_DigestUpdate(p->ctx,d,n)==1?0:-1;}
static inline int psa_hash_finish(psa_hash_operation_t*p,uint8_t*out,size_t cap,size_t*n){unsigned size=0;if(cap<32)return-1;int rc=EVP_DigestFinal_ex(p->ctx,out,&size);*n=size;return rc==1?0:-1;}
static inline int psa_hash_abort(psa_hash_operation_t*p){EVP_MD_CTX_free(p->ctx);p->ctx=NULL;return 0;}
''',
 'bindings.h':'#include "loader_contract.h"\nstatic const struct loader_contract_record vimar_loader_contracts[]={{.kind=LOADER_CONTRACT_COMMON_CODE44K_ANCHOR_V1,.digest={'+','.join(str(v) for v in family)+'}}};\n#define VIMAR_LOADER_CONTRACT_COUNT 1U\n'}
 for name,value in headers.items():p=d/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value)
 source=d/'provider.c';source.write_text(r'''
#include "loader_runtime_zephyr.c"
#include <assert.h>
struct ficr local_ficr;struct device fake_flash;static uint8_t flash_bytes[0xc000],uicr_digest[32];static int io_error;
void setup(const uint8_t*flash,const uint32_t uid[2],const uint8_t*uicr){memcpy(flash_bytes,flash,sizeof(flash_bytes));memcpy(uicr_digest,uicr,32);local_ficr=(struct ficr){.INFO={0x52840,0x41414430,256},.uid={uid[0],uid[1]},.page_size=4096,.page_count=256};fake_flash.ready=1;io_error=0;}
void fault(unsigned n){if(n==1)local_ficr.uid[0]^=1;if(n==2)uicr_digest[0]^=1;if(n==3)local_ficr.INFO.PART=0x52832;if(n==4)local_ficr.INFO.RAM=128;if(n==5)local_ficr.page_count=128;if(n==6)local_ficr.page_size=2048;if(n==7)fake_flash.ready=0;if(n==8)io_error=-5;if(n==9)flash_bytes[17]^=1;if(n==10)flash_bytes[0xb000+252]^=1;}
int flash_read(const struct device*d,uint32_t address,void*out,size_t n){assert(d==&fake_flash&&address<=0xc000&&n<=0xc000-address);if(io_error)return io_error;memcpy(out,flash_bytes+address,n);return 0;}
int ota_image_sha256(const uint8_t*p,size_t n,uint8_t out[32]){assert(p==(const uint8_t*)0x10001000&&n==4096);memcpy(out,uicr_digest,32);return 0;}
int ota_image_verify_primary_for_profile(const uint8_t*p,size_t n,unsigned profile,struct ota_image_info*out){(void)p;(void)n;(void)profile;(void)out;assert(0);return-1;}
''')
 from test_loader_runtime_config import GOOD
 flags={k:v for k,v in GOOD.items() if not k.startswith('CONFIG_MCUMGR')};flags['VIMAR_LOADER_CONTRACT_BINDINGS_HEADER']='"bindings.h"'
 library=d/'provider.so';subprocess.run(['cc','-shared','-fPIC','-std=c11','-O1','-Wall','-Wextra','-Werror','-fsanitize=undefined',*[f'-D{k}={v}' for k,v in flags.items()],'-I'+str(d),'-I'+str(ROOT/'firmware/loader_contract'),'-I'+str(ROOT/'firmware/ota'),str(source),*[str(ROOT/'firmware/loader_contract'/n) for n in ('loader_contract.c','loader_runtime.c','loader_pair.c')],'-lcrypto','-o',str(library)],check=True,capture_output=True)
 lib=c.CDLL(str(library));lib.setup.argtypes=[c.c_void_p,c.c_void_p,c.c_void_p];lib.loader_runtime_zephyr_snapshot.argtypes=[c.POINTER(Snapshot)]
 lib.loader_pair_authenticate_zephyr.argtypes=[c.c_void_p,c.POINTER(Info)]
 lib.loader_pair_verify_zephyr.argtypes=[c.c_void_p,c.c_void_p,c.POINTER(Info)]
 return lib

@pytest.mark.parametrize('uid',[(0x12345678,0x90abcdef),(7,8)])
def test_provider_measures_same_compiled_family_for_two_valid_local_anchors(provider,uid):
 page,live,_,_=fixture(uid=uid);provider.setup(CODE+page,live.uid,live.uicr_sha256);out=Snapshot()
 assert provider.loader_runtime_zephyr_snapshot(c.byref(out))==0
 assert list(out.uid)==list(uid) and out.kind==2 and bytes(out.digest)==hashlib.sha256(DOMAIN+CODE).digest() and bytes(out.anchor_sha256)==hashlib.sha256(page).digest()

@pytest.mark.parametrize('fault',range(1,11))
def test_provider_rejects_bad_local_identity_geometry_anchor_family_or_io(provider,fault):
 page,live,_,_=fixture();provider.setup(CODE+page,live.uid,live.uicr_sha256);provider.fault(fault);out=Snapshot();c.memset(c.byref(out),0xa5,c.sizeof(out))
 assert provider.loader_runtime_zephyr_snapshot(c.byref(out))<0 and bytes(out)==bytes(c.sizeof(out))

def test_missing_operation_hash_clears_provider_identity_without_generic_admission(provider):
 page,live,_,_=fixture();provider.setup(CODE+page,live.uid,live.uicr_sha256)
 loader=(c.c_uint8*32)(*([0xa5]*32));recovery=Info();c.memset(c.byref(recovery),0xa5,c.sizeof(recovery))
 assert provider.loader_pair_verify_zephyr(None,loader,c.byref(recovery))==-errno.EINVAL
 assert bytes(loader)==bytes(32) and bytes(recovery)==bytes(c.sizeof(recovery))

@pytest.mark.parametrize('exact_operation',[False,True])
def test_unavailable_flash_never_publishes_generic_or_exact_provider_identity(provider,exact_operation):
 page,live,_,_=fixture();provider.setup(CODE+page,live.uid,live.uicr_sha256);provider.fault(7)
 loader=(c.c_uint8*32)(*([0xa5]*32));recovery=Info();c.memset(c.byref(recovery),0xa5,c.sizeof(recovery))
 if exact_operation:rc=provider.loader_pair_verify_zephyr(bytes(32),loader,c.byref(recovery))
 else:rc=provider.loader_pair_authenticate_zephyr(loader,c.byref(recovery))
 assert rc==-errno.ENODEV and bytes(loader)==bytes(32) and bytes(recovery)==bytes(c.sizeof(recovery))
