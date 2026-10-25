/* SPDX-License-Identifier: Apache-2.0
 * Isolated stock-maintenance adapter: no settings subsystem or background
 * persistent state. This is deliberately not vimar_power_protection.c.
 */
#include "config_guard.h"
#include "platform_zephyr.h"
#include "bootstrap.h"
#include "monitor.h"
#include "finalizer_core.h"
#include <errno.h>
#include <string.h>
#include <hal/nrf_gpio.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/drivers/flash.h>
#include <zephyr/kernel.h>
#include <zephyr/random/random.h>
#include <zephyr/retention/bootmode.h>
#include <zephyr/sys/atomic.h>
#include <zephyr/sys/reboot.h>
#include <psa/crypto.h>
#ifndef VIMAR_LOADER_CONTRACT_BINDINGS_HEADER
#error "An explicit finite common loader-family binding header is required"
#endif
#include VIMAR_LOADER_CONTRACT_BINDINGS_HEADER
#if defined(CONFIG_VIMAR_COMMON_RESTORE_BOOTSTRAP)
#ifndef VIMAR_COMMON_RESTORE_BLOB_HEADER
#error "Stock bootstrap requires an explicit immutable RESTORE blob header"
#endif
#include VIMAR_COMMON_RESTORE_BLOB_HEADER
#endif
BUILD_ASSERT(VIMAR_LOADER_CONTRACT_COUNT>0&&VIMAR_LOADER_CONTRACT_COUNT<=COMMON_RESTORE_MAX_FAMILIES);
struct common_restore common_restore_state;
static const struct device *flash=DEVICE_DT_GET(DT_CHOSEN(zephyr_flash_controller));
static struct {
 struct common_restore_monitor monitor;
 uint32_t rtc_last;
 uint64_t rtc_epoch_ms;
 bool force_maintenance;
 psa_hash_operation_t hash;
} platform;
static struct k_spinlock monitor_lock;
static atomic_t peer,connected,quiescing;
static uint32_t operation_owner;
volatile uint32_t common_restore_ram_marker;

static COMMON_RESTORE_RAM void force_off(void)
{NRF_P0->OUTCLR=1u<<14;NRF_P0->DIRSET=1u<<14;}
static COMMON_RESTORE_RAM uint64_t rtc_now(void)
{
 uint32_t ticks=NRF_RTC2->COUNTER&0xffffffu;
 if(ticks<platform.rtc_last)platform.rtc_epoch_ms+=UINT64_C(16384000);
 platform.rtc_last=ticks;
 return platform.rtc_epoch_ms+((ticks*125u)>>7); /* RTC2=1024Hz; no division helper */
}
static COMMON_RESTORE_RAM int ram_guard(void *ctx)
{
 (void)ctx;common_restore_monitor_sample(&platform.monitor,rtc_now(),(int)((NRF_P0->IN>>31)&1u));
 if(platform.force_maintenance||platform.monitor.armed||platform.monitor.cancelled||candidate_power_protection_blocked(&platform.monitor.policy))force_off();
 return common_restore_monitor_guard(&platform.monitor);
}
static void sample(struct k_timer *timer)
{ARG_UNUSED(timer);k_spinlock_key_t key=k_spin_lock(&monitor_lock);(void)ram_guard(NULL);k_spin_unlock(&monitor_lock,key);}
K_TIMER_DEFINE(monitor_timer,sample,NULL);
static int guard(void *ctx)
{
 ARG_UNUSED(ctx);k_spinlock_key_t key=k_spin_lock(&monitor_lock);int rc=ram_guard(NULL);k_spin_unlock(&monitor_lock,key);
 if(!rc&&NRF_WDT->RUNSTATUS)rc=-EACCES;
 if(!rc&&!atomic_get(&quiescing)&&(!atomic_get(&connected)||(uint32_t)atomic_get(&peer)!=operation_owner))rc=-ECANCELED;
 return rc;
}
static int arm(void *ctx)
{
 ARG_UNUSED(ctx);
 if(!atomic_get(&connected)||(uint32_t)atomic_get(&peer)!=operation_owner||NRF_WDT->RUNSTATUS)return-EACCES;
 k_spinlock_key_t key=k_spin_lock(&monitor_lock);
 force_off();(void)ram_guard(NULL);int rc=common_restore_monitor_arm(&platform.monitor);
 if(!rc)platform.force_maintenance=true;
 k_spin_unlock(&monitor_lock,key);return rc;
}
static int crypto_guard(void)
{
 if(common_restore_state.phase>=COMMON_RESTORE_WRITING&&common_restore_state.phase<=COMMON_RESTORE_FINALIZING)return guard(NULL);
 return 0; /* read-only admission/table transfer may still report a blocked unit */
}
static int hash_begin(void *ctx)
{ARG_UNUSED(ctx);platform.hash=psa_hash_operation_init();int rc=crypto_guard();if(rc)return rc;
 return psa_hash_setup(&platform.hash,PSA_ALG_SHA_256)==PSA_SUCCESS?0:-EIO;}
static int hash_update(void *ctx,const uint8_t *p,size_t n)
{ARG_UNUSED(ctx);int rc=crypto_guard();if(rc)return rc;return psa_hash_update(&platform.hash,p,n)==PSA_SUCCESS?0:-EIO;}
static int hash_finish(void *ctx,uint8_t out[32])
{ARG_UNUSED(ctx);size_t n=0;int rc=crypto_guard();if(rc)return rc;return psa_hash_finish(&platform.hash,out,32,&n)==PSA_SUCCESS&&n==32?0:-EIO;}
static void hash_abort(void *ctx){ARG_UNUSED(ctx);(void)psa_hash_abort(&platform.hash);}
static int read_flash(void *ctx,uint32_t off,uint8_t *p,size_t n)
{ARG_UNUSED(ctx);if(!p||off>LOADER_CONTRACT_FLASH_SIZE||n>LOADER_CONTRACT_FLASH_SIZE-off||n>LOADER_CONTRACT_PAGE_SIZE)return-EINVAL;return flash_read(flash,off,p,n);}
static int live(void *ctx,struct loader_contract_live *out)
{
 ARG_UNUSED(ctx);size_t n=0;
 struct loader_contract_live value={.part=NRF_FICR->INFO.PART,.variant=NRF_FICR->INFO.VARIANT,
  .uid={NRF_FICR->DEVICEID[0],NRF_FICR->DEVICEID[1]},.flash_size=NRF_FICR->INFO.FLASH*1024u,
  .page_size=NRF_FICR->CODEPAGESIZE,.ram_size=NRF_FICR->INFO.RAM*1024u,.uicr_size=0x1000};
 if(psa_hash_compute(PSA_ALG_SHA_256,(const void *)0x10001000,4096,value.uicr_sha256,32,&n)!=PSA_SUCCESS||n!=32)return-EIO;
 *out=value;return 0;
}
static bool write_address(uint32_t address,size_t n)
{
 if(address>LOADER_CONTRACT_FLASH_SIZE||n>LOADER_CONTRACT_FLASH_SIZE-address)return false;
#if defined(CONFIG_VIMAR_COMMON_RESTORE_BOOTSTRAP)
 return address>=LOADER_CONTRACT_SCRATCH_START&&address+n<=LOADER_CONTRACT_SCRATCH_END;
#else
 return address>=LOADER_CONTRACT_LOADER_SIZE&&!(address<LOADER_CONTRACT_SCRATCH_END&&address+n>LOADER_CONTRACT_SCRATCH_START);
#endif
}
static int erase_page(void *ctx,uint32_t address,size_t n)
{
 ARG_UNUSED(ctx);if(n!=4096||address%4096||!write_address(address,n))return-EINVAL;
 int rc=guard(NULL);if(!rc)rc=flash_erase(flash,address,n);
 if(!rc)rc=guard(NULL);
 k_yield();return rc;
}
static int write_word(void *ctx,uint32_t address,const uint8_t *p,size_t n)
{ARG_UNUSED(ctx);if(!p||n!=4||address%4||!write_address(address,n))return-EINVAL;int rc=guard(NULL);return rc?rc:flash_write(flash,address,p,n);}
static bool peripherals_quiet(void)
{
 return NRF_CLOCK->LFCLKSTAT&& !NRF_WDT->RUNSTATUS&&!NRF_RADIO->STATE&&!NRF_SPIM0->ENABLE&&!NRF_SPIM1->ENABLE&&
  !NRF_SPIM2->ENABLE&&!NRF_SPIM3->ENABLE&&!NRF_UARTE0->ENABLE&&!NRF_UARTE1->ENABLE&&
  !NRF_SAADC->ENABLE&&!NRF_PDM->ENABLE&&!NRF_I2S->ENABLE&&!NRF_PWM0->ENABLE&&
  !NRF_PWM1->ENABLE&&!NRF_PWM2->ENABLE&&!NRF_PWM3->ENABLE;
}
static int quiesce(void *ctx)
{
 ARG_UNUSED(ctx);int rc=guard(NULL);if(rc)return rc;
 atomic_set(&quiescing,1);rc=bt_disable();
 if(rc){atomic_set(&quiescing,0);return rc;}
 if(!peripherals_quiet())return-EBUSY;
 return guard(NULL);
}
static COMMON_RESTORE_RAM int wait_ready(void)
{
 int failed=0;
 while(!NRF_NVMC->READY){int rc=ram_guard(NULL);if(rc)failed=rc;force_off();}
 return failed;
}
static COMMON_RESTORE_RAM int ram_erase(void *ctx,uint32_t address)
{
 ARG_UNUSED(ctx);int rc=ram_guard(NULL);if(rc)return rc;
 NRF_NVMC->CONFIG=2;__DSB();__ISB();rc=wait_ready();if(rc)return rc;
 NRF_NVMC->ERASEPAGE=address;return wait_ready();
}
static COMMON_RESTORE_RAM int ram_write(void *ctx,uint32_t address,uint32_t value)
{
 ARG_UNUSED(ctx);int rc=ram_guard(NULL);if(rc)return rc;
 NRF_NVMC->CONFIG=1;__DSB();__ISB();rc=wait_ready();if(rc)return rc;
 __asm__ volatile("str %1, [%0]"::"r"(address),"r"(value):"memory");return wait_ready();
}
static COMMON_RESTORE_RAM int ram_read(void *ctx,uint32_t address,uint32_t *out)
{ARG_UNUSED(ctx);__asm__ volatile("ldr %0, [%1]":"=r"(*out):"r"(address):"memory");return 0;}
static COMMON_RESTORE_RAM bool in_ram(uintptr_t pointer,size_t size)
{return pointer>=0x20000000u&&pointer<=0x20040000u&&size<=0x20040000u-pointer;}
static COMMON_RESTORE_RAM __noreturn void ram_entry(const uint8_t *boot,size_t size)
{
 uintptr_t stack;__asm__ volatile("mov %0, sp":"=r"(stack));
 __asm__ volatile("cpsid i\n\tcpsid f":::"memory");__DSB();__ISB();force_off();
 common_restore_ram_marker=0x10000000u;
 if(size!=LOADER_CONTRACT_LOADER_SIZE||((uintptr_t)boot&3)||!in_ram((uintptr_t)boot,size)||!in_ram(stack,64)||stack<0x20000400u||
    !in_ram((uintptr_t)&platform,sizeof(platform))||
    !in_ram((uintptr_t)ram_guard&~(uintptr_t)1,2)||
    !in_ram((uintptr_t)ram_erase&~(uintptr_t)1,2)||
    !in_ram((uintptr_t)ram_write&~(uintptr_t)1,2)||
    !in_ram((uintptr_t)ram_read&~(uintptr_t)1,2)||
    !in_ram((uintptr_t)wait_ready&~(uintptr_t)1,2)||
    !in_ram((uintptr_t)rtc_now&~(uintptr_t)1,2)||
    !in_ram((uintptr_t)force_off&~(uintptr_t)1,2)||
    !in_ram((uintptr_t)common_restore_monitor_sample&~(uintptr_t)1,2)||
    !in_ram((uintptr_t)common_restore_monitor_guard&~(uintptr_t)1,2)||
    !in_ram((uintptr_t)common_restore_finalizer_core&~(uintptr_t)1,2)||
    !in_ram((uintptr_t)candidate_power_protection_sample&~(uintptr_t)1,2)||
    !in_ram((uintptr_t)candidate_power_protection_blocked&~(uintptr_t)1,2))goto failure;
 struct common_restore_final_io ops={.guard=ram_guard,.erase_page=ram_erase,.write_word=ram_write,.read_word=ram_read};
 NRF_NVMC->ICACHECNF=0;__DSB();__ISB();
 if(wait_ready()||common_restore_finalizer_core(boot,size,&ops,&common_restore_ram_marker))goto failure;
 NRF_NVMC->CONFIG=0;__DSB();__ISB();
 *(volatile uint32_t *)0xe000ed08u=0;
 *(volatile uint32_t *)0xe000ed0cu=0x05fa0004u|(*(volatile uint32_t *)0xe000ed0cu&0x700u);
 __DSB();__ISB();for(;;){__asm__ volatile("nop");}
failure:
 common_restore_ram_marker|=0xe0000000u;
 while(!NRF_NVMC->READY){force_off();(void)ram_guard(NULL);}
 NRF_NVMC->CONFIG=0;__DSB();__ISB();for(;;){force_off();(void)ram_guard(NULL);__asm__ volatile("nop");}
}
static int finalize(void *ctx,const uint8_t *boot,size_t n)
{ARG_UNUSED(ctx);if(!peripherals_quiet())return-EBUSY;int rc=guard(NULL);if(rc)return rc;ram_entry(boot,n);}
static int admit_bootstrap(void *ctx)
{
 ARG_UNUSED(ctx);
#if defined(CONFIG_VIMAR_COMMON_RESTORE_BOOTSTRAP)
 return common_restore_bootstrap_validate(common_restore_blob,sizeof(common_restore_blob));
#else
 return-EACCES;
#endif
}
static int request_loader(void *ctx)
{ARG_UNUSED(ctx);int rc=guard(NULL);if(!rc)rc=bootmode_set(BOOT_MODE_TYPE_BOOTLOADER);if(rc)return rc;sys_reboot(SYS_REBOOT_COLD);return-EIO;}
static const struct common_restore_io io={
 .flash={.size=LOADER_CONTRACT_FLASH_SIZE,.read=read_flash},
 .hash={.begin=hash_begin,.update=hash_update,.finish=hash_finish,.abort=hash_abort},
 .live=live,.guard=guard,.arm=arm,.erase=erase_page,.write=write_word,.quiesce=quiesce,.finalize=finalize,
 .bootstrap=IS_ENABLED(CONFIG_VIMAR_COMMON_RESTORE_BOOTSTRAP),.admit_bootstrap=admit_bootstrap,.request_loader=request_loader
};
int common_restore_platform_init(void)
{
 if(!IS_ENABLED(CONFIG_VIMAR_COMMON_RESTORE_BOOTSTRAP))force_off();
 if(!device_is_ready(flash)||psa_crypto_init()!=PSA_SUCCESS){force_off();return-EIO;}
 nrf_gpio_cfg_input(31,NRF_GPIO_PIN_NOPULL);
 NRF_RTC2->TASKS_STOP=1;NRF_RTC2->TASKS_CLEAR=1;NRF_RTC2->PRESCALER=31;NRF_RTC2->TASKS_START=1;
 k_sleep(K_MSEC(3));if(!NRF_RTC2->COUNTER){force_off();return-EIO;}
 common_restore_monitor_init(&platform.monitor);platform.force_maintenance=!IS_ENABLED(CONFIG_VIMAR_COMMON_RESTORE_BOOTSTRAP);
 (void)ram_guard(NULL);k_timer_start(&monitor_timer,K_MSEC(30),K_MSEC(30));return 0;
}
const struct common_restore_io *common_restore_platform_io(void){return &io;}
void common_restore_platform_peer(uint32_t owner,bool alive){atomic_set(&peer,(atomic_val_t)owner);atomic_set(&connected,alive);}
void common_restore_platform_operation(uint32_t owner){operation_owner=owner;atomic_set(&quiescing,0);}
bool common_restore_platform_quiescing(void){return atomic_get(&quiescing)!=0;}
unsigned common_restore_platform_flags(void)
{k_spinlock_key_t key=k_spin_lock(&monitor_lock);unsigned flags=(platform.monitor.armed?1:0)|(platform.monitor.cancelled?2:0)|(candidate_power_protection_blocked(&platform.monitor.policy)?4:0);k_spin_unlock(&monitor_lock,key);return flags;}
const struct loader_contract_record *common_restore_platform_records(size_t *count){*count=VIMAR_LOADER_CONTRACT_COUNT;return vimar_loader_contracts;}
unsigned common_restore_platform_role(void){return IS_ENABLED(CONFIG_VIMAR_COMMON_RESTORE_BOOTSTRAP)?3:4;}
void common_restore_platform_blob(const uint8_t **p,size_t *n)
{
#if defined(CONFIG_VIMAR_COMMON_RESTORE_BOOTSTRAP)
 *p=common_restore_blob;*n=sizeof(common_restore_blob);
#else
 *p=NULL;*n=0;
#endif
}
