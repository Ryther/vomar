#include <assert.h>
#include <stdint.h>
#include <string.h>
#include <bootutil/bootutil.h>
static int verification, protection_calls, hash_error;
static uint8_t hash_value=1;
static uint32_t selected=0xb0000;
int __real_boot_go(struct boot_rsp *rsp) {rsp->br_image_off=selected;rsp->br_flash_dev_id=0;return verification;}
int __real_fprotect_area(uint32_t start,size_t length) {(void)start;(void)length;++protection_calls;return 17;}
int bootutil_sha_init(int *c) {(void)c;return hash_error;}
int bootutil_sha_update(int *c,const void *p,uint32_t n) {(void)c;assert(p==(void*)0xb0000);assert(n==185803);return 0;}
int bootutil_sha_finish(int *c,uint8_t *out) {(void)c;memset(out,0,32);out[0]=hash_value;return 0;}
int bootutil_sha_drop(int *c) {(void)c;return 0;}
int __wrap_boot_go(struct boot_rsp *rsp);
int __wrap_fprotect_area(uint32_t start,size_t length);
int main(void) {
 struct boot_rsp rsp;
 assert(__wrap_fprotect_area(0,0xc000)==17);
 assert(__wrap_boot_go(&rsp)==0);
 assert(__wrap_fprotect_area(0,0xc000)==0);
 assert(__wrap_fprotect_area(0x1000,0xb000)==17);
 verification=-1;assert(__wrap_boot_go(&rsp)==-1);assert(__wrap_fprotect_area(0,0xc000)==17);
 verification=0;selected=0xc000;assert(__wrap_boot_go(&rsp)==0);assert(__wrap_fprotect_area(0,0xc000)==17);
 selected=0xb0000;hash_value=2;assert(__wrap_boot_go(&rsp)==0);assert(__wrap_fprotect_area(0,0xc000)==17);
 hash_value=1;hash_error=-1;assert(__wrap_boot_go(&rsp)==0);assert(__wrap_fprotect_area(0,0xc000)==17);
 assert(protection_calls==6);
 return 0;
}
