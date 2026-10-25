#include "boot_trace.h"
#include <assert.h>
#include <string.h>
int main(void){
 struct boot_trace trace={0},decoded;
 boot_trace_request(&trace,BOOT_REASON_ZIGBEE);
 boot_trace_begin(&trace,BOOT_IMAGE_RECOVERY,4);
 const struct boot_trace_entry *e=boot_trace_last(&trace);
 assert(e&&e->reason==BOOT_REASON_ZIGBEE&&e->reset_flags==4&&trace.pending_reason==0);
 boot_trace_request(&trace,BOOT_REASON_CHORD);boot_trace_begin(&trace,BOOT_IMAGE_MAIN,1);
 assert(boot_trace_last(&trace)->reason==BOOT_REASON_MAIN_START);
 boot_trace_begin(&trace,BOOT_IMAGE_RECOVERY,2);
 assert(boot_trace_last(&trace)->reason==BOOT_REASON_RECOVERY_UNKNOWN);
 for(unsigned i=0;i<20;i++)boot_trace_begin(&trace,BOOT_IMAGE_MAIN,i);
 assert(trace.count==BOOT_TRACE_ENTRIES&&boot_trace_last(&trace)->sequence==23);
 uint8_t record[BOOT_TRACE_RECORD_SIZE],bad[BOOT_TRACE_RECORD_SIZE];
 boot_trace_encode(&trace,record);
 assert(boot_trace_decode(record,sizeof(record),&decoded)==0);
 assert(boot_trace_last(&decoded)->sequence==23);
 for(unsigned i=0;i<sizeof(record);i++){
  memcpy(bad,record,sizeof(bad));bad[i]^=1;
  assert(boot_trace_decode(bad,sizeof(bad),&decoded)<0&&decoded.count==0);
 }
 assert(boot_trace_decode(record,sizeof(record)-1,&decoded)<0);
 trace.sequence=UINT32_MAX;boot_trace_begin(&trace,BOOT_IMAGE_MAIN,0);
 assert(boot_trace_last(&trace)->sequence==UINT32_MAX);
 return 0;
}
