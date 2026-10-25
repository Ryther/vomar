/* SPDX-License-Identifier: Apache-2.0 */
#if __has_include("monitor.h") && __has_include("finalizer_core.h")
#include "monitor.h"
#include "finalizer_core.h"
#define HAVE_MONITOR 1
#endif
#include <errno.h>
#include <stdint.h>
#include <string.h>
#ifdef HAVE_MONITOR
static struct common_restore_monitor monitor;
static uint8_t flash[0x100000],original[0x100000],boot[0xc000];
static unsigned erases,writes,mutations,outside,failure_step;
static int readback_failure;
static int guard(void *ctx){(void)ctx;return failure_step&&mutations+1==failure_step?-ECANCELED:0;}
static int erase(void *ctx,uint32_t address){(void)ctx;
 if(address%4096||!(address<0xc000||(address>=0xb0000&&address<0xef000))){outside++;return-EINVAL;}
 mutations++;erases++;memset(flash+address,0xff,4096);return 0;}
static int write_word(void *ctx,uint32_t address,uint32_t value){(void)ctx;
 if(address%4||address>=0xc000){outside++;return-EINVAL;}mutations++;writes++;
 memcpy(flash+address,&value,4);if(readback_failure)flash[address]^=1;return 0;}
static int read_word(void *ctx,uint32_t address,uint32_t *out){(void)ctx;
 if(address%4||!(address<0xc000||(address>=0xb0000&&address<0xef000))){outside++;return-EINVAL;}
 memcpy(out,flash+address,4);return 0;}
int monitor_init(void){common_restore_monitor_init(&monitor);return 0;}
void monitor_sample(uint64_t now,int raw){common_restore_monitor_sample(&monitor,now,raw);}
int monitor_arm(void){return common_restore_monitor_arm(&monitor);}
int monitor_guard(void){return common_restore_monitor_guard(&monitor);}
int final_run(unsigned failure,int mismatch){
 for(unsigned i=0;i<sizeof(original);i++)original[i]=(uint8_t)(i*17u+(i/4096u)*11u);
 memset(original+0xb0000,0xff,0x3f000);memcpy(flash,original,sizeof(flash));memcpy(boot,original,sizeof(boot));
 memset(flash,0x71,sizeof(boot));memset(flash+0xb0000,0x22,0x3f000);
 erases=writes=mutations=outside=0;failure_step=failure;readback_failure=mismatch;
 struct common_restore_final_io io={NULL,guard,erase,write_word,read_word};
 return common_restore_finalizer_core(boot,sizeof(boot),&io,NULL);
}
unsigned final_erases(void){return erases;}
unsigned final_writes(void){return writes;}
unsigned final_mutations(void){return mutations;}
unsigned final_outside(void){return outside;}
int final_matches(void){return !memcmp(flash,original,sizeof(flash));}
#else
int monitor_init(void){return-ENOSYS;}
void monitor_sample(uint64_t now,int raw){(void)now;(void)raw;}
int monitor_arm(void){return-ENOSYS;}
int monitor_guard(void){return-ENOSYS;}
int final_run(unsigned failure,int mismatch){(void)failure;(void)mismatch;return-ENOSYS;}
unsigned final_erases(void){return 0;}
unsigned final_writes(void){return 0;}
unsigned final_mutations(void){return 0;}
unsigned final_outside(void){return 0;}
int final_matches(void){return 0;}
#endif
