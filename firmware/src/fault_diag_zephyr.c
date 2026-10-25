#include "fault_diag_zephyr.h"
#include "fault_diag.h"
#include <zephyr/kernel.h>
#include <zephyr/settings/settings.h>
#include <hal/nrf_power.h>
#include <string.h>
#include <errno.h>
#include VIMAR_FAULT_BUILD_ID_HEADER

#ifndef RETAINED
/* Legacy loaders initialize libc's heap footer at0x2003fff8. Leave the
 * entire top256 bytes outside this window; static ELF bounds alone miss it.
 * Retention remains best effort through a pinned legacy loader's free arena. */
#define RETAINED ((volatile uint32_t *)UINT32_C(0x2003fe00))
#endif
static struct fault_diag_context diag;
static struct fault_diag_breadcrumb crumb;
static uint32_t exported[FAULT_DIAG_WINDOW_WORDS];
static uint32_t export_status;
static bool ready;

/* Decode foreign build evidence as foreign: the stored identity is retained
 * verbatim for later matching to its archived ELF, never attributed to this
 * build. This is forensic data, not authority to execute an image. */
static bool read_stored(const volatile uint32_t *words,unsigned slot,struct fault_diag_record *record)
{
    uint32_t stored_id[4];
    for(unsigned i=0;i<4;i++)stored_id[i]=words[slot*32+4+i];
    return fault_diag_read(words,slot,(const uint8_t *)stored_id,record);
}
static bool valid_pair(const volatile uint32_t *words)
{
    struct fault_diag_record record;
    return read_stored(words,0,&record) | read_stored(words,1,&record);
}

void vimar_fault_diag_boot(uint32_t boot_sequence)
{
    uint32_t saved[FAULT_DIAG_WINDOW_WORDS];
    fault_diag_init(&diag,RETAINED,vimar_fault_build_id,boot_sequence);
    ssize_t n=settings_load_one("vimar/fault_diag",saved,sizeof(saved));
    if(n==(ssize_t)sizeof(saved) && valid_pair(saved)) {
        memcpy(exported,saved,sizeof(exported));export_status=2u|4u;
    } else if(n<0 && n!=-ENOENT) export_status|=8u;
    if(valid_pair(RETAINED)) {
        /* A reset between the two commit-clearing stores leaves a subset of
         * an already persisted pair. Keep the whole durable pair in that case. */
        bool durable_subset=(export_status&4u)!=0;
        for(unsigned slot=0;slot<2;slot++) {
            struct fault_diag_record record;
            if(read_stored(RETAINED,slot,&record) &&
               memcmp((uint8_t *)exported+slot*128,&record,128)!=0)durable_subset=false;
        }
        /* Export only validated slots; never attach validity to uncommitted RAM. */
        if(!durable_subset)memset(exported,0,sizeof(exported));
        for(unsigned slot=0;slot<2;slot++) {
            struct fault_diag_record record;
            if(read_stored(RETAINED,slot,&record))
                memcpy((uint8_t *)exported+slot*128,&record,128);
        }
        export_status=2u;
        int rc=settings_save_one("vimar/fault_diag",exported,sizeof(exported));
        if(rc==0) {
            n=settings_load_one("vimar/fault_diag",saved,sizeof(saved));
            if(n==(ssize_t)sizeof(saved) && memcmp(saved,exported,sizeof(saved))==0) {
                export_status|=4u;fault_diag_acknowledge(&diag);
            } else export_status|=8u;
        } else export_status|=8u;
    }
    for(unsigned slot=0;slot<2;slot++) {
        struct fault_diag_record record;
        if(read_stored(exported,slot,&record)) {
            if(memcmp(record.build_id,vimar_fault_build_id,16)!=0)export_status|=32u;
            uint32_t delta=record.sequence-diag.sequence;
            if(diag.sequence==0u || (delta!=0u && delta<UINT32_C(0x80000000)))diag.sequence=record.sequence;
        }
    }
    if(!diag.blocked)export_status|=1u;else export_status|=16u;
    crumb=(struct fault_diag_breadcrumb){.stage=1,.valid=FAULT_DIAG_VALID_STAGE};
    fault_diag_breadcrumb(&diag,&crumb);ready=true;
}

void vimar_fault_diag_signal(uint32_t signal,int32_t status,uint32_t role)
{
    if(!ready)return;
    unsigned key=irq_lock();
    crumb.signal=signal;crumb.signal_status=status;crumb.role=role;crumb.stage=2;
    crumb.valid|=FAULT_DIAG_VALID_SIGNAL|FAULT_DIAG_VALID_SIGNAL_STATUS|FAULT_DIAG_VALID_ROLE|FAULT_DIAG_VALID_STAGE;
    fault_diag_breadcrumb(&diag,&crumb);irq_unlock(key);
}
void vimar_fault_diag_tick(uint32_t uptime_ms)
{
    if(!ready)return;
    unsigned key=irq_lock();crumb.uptime_ms=uptime_ms;crumb.valid|=FAULT_DIAG_VALID_UPTIME;
    fault_diag_breadcrumb(&diag,&crumb);irq_unlock(key);
}
void vimar_fault_diag_report(uint32_t kind,uint32_t length,int32_t status)
{
    if(!ready)return;
    unsigned key=irq_lock();crumb.report_kind=kind&0x7fffffffu;crumb.report_length=length;crumb.report_status=status;
    crumb.phase=(kind&0x80000000u)?2u:(status==INT32_MIN?0u:1u);
    crumb.valid|=FAULT_DIAG_VALID_REPORT_KIND|FAULT_DIAG_VALID_REPORT_LENGTH|FAULT_DIAG_VALID_REPORT_STATUS|FAULT_DIAG_VALID_PHASE;
    if(status==INT32_MIN)crumb.valid&=~FAULT_DIAG_VALID_REPORT_STATUS;
    fault_diag_breadcrumb(&diag,&crumb);irq_unlock(key);
}
void vimar_fault_diag_error(uint32_t site,int32_t line,int32_t rc)
{if(!ready)return;uint32_t key=__get_PRIMASK();__disable_irq();(void)fault_diag_capture_error(&diag,site,line,rc);__set_PRIMASK(key);}
void vimar_fault_diag_assert(uint32_t file_id,int32_t line)
{if(!ready)return;uint32_t key=__get_PRIMASK();__disable_irq();(void)fault_diag_capture_assert(&diag,file_id,line);__set_PRIMASK(key);}
void vimar_fault_diag_abort(uint32_t lr,uint32_t msp,uint32_t psp,uint32_t ipsr)
{
    if(!ready)return;
    uint32_t key=__get_PRIMASK();__disable_irq();
    uint32_t gp=nrf_power_gpregret_get(NRF_POWER,0)|(nrf_power_gpregret_get(NRF_POWER,1)<<8);
    (void)fault_diag_capture_abort(&diag,lr,msp,psp,ipsr,__get_CONTROL(),gp);
    __set_PRIMASK(key);
}
void vimar_fault_diag_export(uint8_t chunks[8][33],uint32_t *status)
{
    *status=export_status;
    for(unsigned i=0;i<8;i++){chunks[i][0]=32;memcpy(chunks[i]+1,(uint8_t *)exported+32*i,32);}
}
