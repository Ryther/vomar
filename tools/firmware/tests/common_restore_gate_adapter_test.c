#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "common_restore_policy.h"
#include <bootutil/bootutil.h>
#include <hal/nrf_ficr.h>
NRF_FICR_Type test_ficr={.CODEPAGESIZE=4096,.CODESIZE=256,.DEVICEID={0x12345678,0x90abcdef},
 .INFO={.PART=0x52840,.VARIANT=0x41414430,.RAM=256}};
static int boot_result,admission_result,hash_error,protection_result=17;
static unsigned device,admit_calls,hash_calls,drop_calls,real_calls;
static uint32_t slot=0xb0000;
int __wrap_fprotect_area(uint32_t,size_t);
fih_ret __wrap_boot_go(struct boot_rsp*);
fih_ret __real_boot_go(struct boot_rsp *rsp){
 /* Every invocation clears any previous privilege before real validation. */
 assert(__wrap_fprotect_area(0,0xc000)==protection_result);
 ++real_calls;
 if(!boot_result){rsp->br_image_off=slot;rsp->br_flash_dev_id=(uint8_t)device;}
 return boot_result;
}
int __real_fprotect_area(uint32_t start,size_t n){(void)start;(void)n;return protection_result;}
int bootutil_sha_init(int *ctx){(void)ctx;++hash_calls;return hash_error;}
int bootutil_sha_update(int *ctx,const void*p,uint32_t n){(void)ctx;assert(p==(const void*)0x10001000);assert(n==4096);return hash_error;}
int bootutil_sha_finish(int *ctx,uint8_t *out){(void)ctx;memset(out,0,32);out[0]=0x42;return hash_error;}
int bootutil_sha_drop(int *ctx){(void)ctx;++drop_calls;return 0;}
int common_restore_admit(bool verified,unsigned dev,uint32_t off,const uint8_t*p,size_t n,
 const uint8_t*a,size_t an,const struct loader_contract_live*live){
 ++admit_calls;assert(verified&&dev==0&&off==0xb0000&&p==(void*)0xb0000&&n==0x3f000);
 assert(a==(void*)0xb000&&an==4096&&live->part==0x52840&&live->variant==0x41414430);
 assert(live->uid[0]==0x12345678&&live->uid[1]==0x90abcdef&&live->flash_size==0x100000);
 assert(live->page_size==4096&&live->ram_size==0x40000&&live->uicr_size==4096&&live->uicr_sha256[0]==0x42);
 return admission_result;
}
int main(void){
 struct boot_rsp rsp={0};
 assert(__wrap_fprotect_area(0,0xc000)==17);
 assert(__wrap_boot_go(&rsp)==0&&real_calls==1&&admit_calls==1&&hash_calls==1&&drop_calls==1);
 assert(__wrap_fprotect_area(0,0xc000)==0);
 assert(__wrap_fprotect_area(1,0xc000)==17);
 assert(__wrap_fprotect_area(0,0xb000)==17);
 assert(__wrap_fprotect_area(0,0xc001)==17);
 boot_result=-7;assert(__wrap_boot_go(&rsp)==-7&&admit_calls==1&&hash_calls==1);
 assert(__wrap_fprotect_area(0,0xc000)==17);
 boot_result=0;slot=0xc000;assert(__wrap_boot_go(&rsp)==0&&admit_calls==1&&hash_calls==1);
 assert(__wrap_fprotect_area(0,0xc000)==17);
 slot=0xb0000;device=1;assert(__wrap_boot_go(&rsp)==0&&admit_calls==1&&hash_calls==1);
 device=0;hash_error=-5;assert(__wrap_boot_go(&rsp)==0&&admit_calls==1);
 assert(__wrap_fprotect_area(0,0xc000)==17);
 hash_error=0;admission_result=-13;assert(__wrap_boot_go(&rsp)==0&&admit_calls==2);
 assert(__wrap_fprotect_area(0,0xc000)==17);
 admission_result=0;assert(__wrap_boot_go(&rsp)==0);assert(__wrap_fprotect_area(0,0xc000)==0);
 protection_result=-23;assert(__wrap_fprotect_area(0x1000,0xb000)==-23);
 boot_result=-9;assert(__wrap_boot_go(&rsp)==-9);assert(__wrap_fprotect_area(0,0xc000)==-23);
 return 0;
}
