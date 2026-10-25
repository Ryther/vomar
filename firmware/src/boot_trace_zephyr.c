#include "boot_trace.h"
#include <errno.h>
#include <string.h>
#include <limits.h>
#include <hal/nrf_power.h>
#include <zephyr/settings/settings.h>
#include <zephyr/kernel.h>
static struct boot_trace trace;
static int32_t load_result,decode_result,save_result;
static bool initialized,loaded_valid,storage_valid;
K_MUTEX_DEFINE(trace_mutex);
static int save(void){uint8_t record[BOOT_TRACE_RECORD_SIZE];boot_trace_encode(&trace,record);int rc=settings_save_one("vimar/boot_trace",record,sizeof(record));save_result=rc;storage_valid=rc==0;return rc;}
int vimar_boot_trace_begin(enum boot_image image)
{
 /* Available raw flags may already have been affected by the loader: do not
  * translate an empty register to a proven power-loss diagnosis. */
 uint32_t flags=nrf_power_resetreas_get(NRF_POWER);
 nrf_power_resetreas_clear(NRF_POWER,flags);
 k_mutex_lock(&trace_mutex,K_FOREVER);
 uint8_t record[BOOT_TRACE_RECORD_SIZE];ssize_t n=settings_load_one("vimar/boot_trace",record,sizeof(record));
 load_result=n>INT32_MAX||n<INT32_MIN?-EOVERFLOW:(int32_t)n;
 decode_result=0;loaded_valid=false;
 if(n>0){decode_result=boot_trace_decode(record,(size_t)n,&trace);loaded_valid=decode_result==0;}else memset(&trace,0,sizeof(trace));
 initialized=true;
 boot_trace_begin(&trace,image,flags);int rc=save();k_mutex_unlock(&trace_mutex);return rc;
}
int vimar_boot_trace_request(enum boot_reason reason)
{k_mutex_lock(&trace_mutex,K_FOREVER);boot_trace_request(&trace,reason);int rc=save();k_mutex_unlock(&trace_mutex);return rc;}
void vimar_boot_trace_snapshot(struct boot_trace_entry *out)
{k_mutex_lock(&trace_mutex,K_FOREVER);const struct boot_trace_entry*last=boot_trace_last(&trace);*out=last?*last:(struct boot_trace_entry){0};k_mutex_unlock(&trace_mutex);}
void vimar_boot_trace_history_snapshot(struct boot_trace_history *out)
{
 if(!out)return;
 struct boot_trace_history history={0};
 k_mutex_lock(&trace_mutex,K_FOREVER);
 history.view_result=boot_trace_chronological(&trace,&history.view);
 history.load_result=load_result;history.decode_result=decode_result;history.save_result=save_result;
 history.initialized=initialized;history.loaded_valid=loaded_valid;
 history.storage_valid=storage_valid&&history.view_result==0;
 k_mutex_unlock(&trace_mutex);
 memcpy(out,&history,sizeof(history));
}
