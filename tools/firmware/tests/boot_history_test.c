#include "boot_trace.h"
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <string.h>
#include <zephyr/kernel.h>
static uint8_t persisted[BOOT_TRACE_RECORD_SIZE];
static size_t stored_length;
static int load_error,save_error;
static uint32_t reset_flags;
static unsigned saves,loads,clears,locks;
extern struct k_mutex trace_mutex;
uint32_t test_resetreas_get(void){return reset_flags;}
void test_resetreas_clear(uint32_t n){assert(n==reset_flags);reset_flags=0;clears++;}
void test_lock(void){locks++;}
ssize_t settings_load_one(const char*k,void*p,size_t n){assert(trace_mutex.depth==1&&!strcmp(k,"vimar/boot_trace"));loads++;if(load_error)return load_error;size_t copy=stored_length<n?stored_length:n;memcpy(p,persisted,copy);return (ssize_t)stored_length;}
int settings_save_one(const char*k,const void*p,size_t n){assert(trace_mutex.depth==1&&!strcmp(k,"vimar/boot_trace")&&n==88);saves++;if(save_error)return save_error;memcpy(persisted,p,n);stored_length=n;return 0;}
static struct boot_trace_history snapshot(void){struct boot_trace_history out;unsigned before_saves=saves,before_loads=loads,before_clears=clears,before_locks=locks;uint8_t record[88];memcpy(record,persisted,88);vimar_boot_trace_history_snapshot(&out);assert(locks==before_locks+1&&saves==before_saves&&loads==before_loads&&clears==before_clears&&!memcmp(record,persisted,88));return out;}
int main(int argc,char**argv){
 assert(argc==2);
 struct boot_trace_history h=snapshot();assert(!h.initialized&&!h.storage_valid&&!h.view.count);
 if(!strcmp(argv[1],"ring")){
  reset_flags=1;assert(!vimar_boot_trace_begin(BOOT_IMAGE_MAIN));h=snapshot();
  assert(h.initialized&&!h.loaded_valid&&h.storage_valid&&h.load_result==0&&h.decode_result==0&&h.save_result==0);
  assert(h.view.count==1&&h.view.entries[0].sequence==1&&h.view.entries[0].reset_flags==1);
  assert(!vimar_boot_trace_request(BOOT_REASON_ZIGBEE));h=snapshot();assert(h.view.pending_reason==BOOT_REASON_ZIGBEE);
  assert(!vimar_boot_trace_begin(BOOT_IMAGE_RECOVERY));h=snapshot();
  assert(h.loaded_valid&&h.load_result==88&&h.view.count==2&&h.view.entries[1].sequence==2);
  assert(h.view.entries[1].reason==BOOT_REASON_ZIGBEE&&h.view.entries[1].reset_flags==0&&!h.view.pending_reason);
  for(unsigned i=0;i<7;i++){reset_flags=i+8;assert(!vimar_boot_trace_begin(BOOT_IMAGE_MAIN));}
  h=snapshot();assert(h.view.count==6&&h.view.sequence==9);
  for(unsigned i=0;i<6;i++)assert(h.view.entries[i].sequence==i+4);
 }else{
  struct boot_trace trace={0};boot_trace_begin(&trace,BOOT_IMAGE_MAIN,7);boot_trace_encode(&trace,persisted);stored_length=88;
  if(!strcmp(argv[1],"crc"))persisted[84]^=1;
  else if(!strcmp(argv[1],"load"))load_error=-EIO;
  else if(!strcmp(argv[1],"save"))save_error=-ENOSPC;
  else assert(0);
  int rc=vimar_boot_trace_begin(BOOT_IMAGE_RECOVERY);h=snapshot();assert(h.initialized);
  if(!strcmp(argv[1],"crc"))assert(!rc&&!h.loaded_valid&&h.storage_valid&&h.load_result==88&&h.decode_result<0&&h.view.count==1);
  if(!strcmp(argv[1],"load"))assert(!rc&&!h.loaded_valid&&h.load_result==-EIO&&h.decode_result==0&&h.view.count==1);
  if(!strcmp(argv[1],"save")){
   assert(rc==-ENOSPC&&h.loaded_valid&&!h.storage_valid&&h.save_result==-ENOSPC&&h.view.count==2);
   save_error=0;assert(!vimar_boot_trace_request(BOOT_REASON_NONE));h=snapshot();assert(h.storage_valid&&h.save_result==0&&h.view.count==2);
  }
 }
 struct boot_trace_entry last;vimar_boot_trace_snapshot(&last);h=snapshot();assert(last.sequence==h.view.entries[h.view.count-1].sequence);
 return 0;
}
