#include "boot_trace.h"
#include <errno.h>
#include <limits.h>
#include <string.h>
static void put32(uint8_t*p,uint32_t n){for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(n>>(8*i));}
static uint32_t get32(const uint8_t*p){return(uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static uint32_t crc32(const uint8_t*p,size_t n){uint32_t crc=UINT32_MAX;for(size_t i=0;i<n;i++){crc^=p[i];for(unsigned b=0;b<8;b++)crc=(crc>>1)^((crc&1)?0xedb88320u:0u);}return~crc;}
void boot_trace_request(struct boot_trace*t,enum boot_reason r)
{if(r>=BOOT_REASON_NONE&&r<=BOOT_REASON_BOOT_SELECTOR)t->pending_reason=(uint8_t)r;}
void boot_trace_begin(struct boot_trace*t,enum boot_image image,uint32_t flags)
{
 enum boot_reason reason=image==BOOT_IMAGE_MAIN?BOOT_REASON_MAIN_START:BOOT_REASON_RECOVERY_UNKNOWN;
 if(image==BOOT_IMAGE_RECOVERY&&(t->pending_reason==BOOT_REASON_ZIGBEE||t->pending_reason==BOOT_REASON_CHORD||t->pending_reason==BOOT_REASON_OTA_INSTALL||t->pending_reason==BOOT_REASON_BOOT_SELECTOR))reason=t->pending_reason;
 if(image==BOOT_IMAGE_MAIN&&t->pending_reason==BOOT_REASON_OTA_COMPLETE)reason=BOOT_REASON_OTA_COMPLETE;
 t->pending_reason=0;if(t->sequence<UINT32_MAX)t->sequence++;
 t->entries[t->next]=(struct boot_trace_entry){.sequence=t->sequence,.reset_flags=flags,.reason=reason,.image=image};
 t->next=(t->next+1)%BOOT_TRACE_ENTRIES;if(t->count<BOOT_TRACE_ENTRIES)t->count++;
}
const struct boot_trace_entry *boot_trace_last(const struct boot_trace*t)
{return t->count?&t->entries[(t->next+BOOT_TRACE_ENTRIES-1)%BOOT_TRACE_ENTRIES]:NULL;}
int boot_trace_chronological(const struct boot_trace*t,struct boot_trace_view*out)
{
 if(!out)return-EINVAL;
 struct boot_trace_view view={0};int rc=-EINVAL;
 if(t&&t->count<=BOOT_TRACE_ENTRIES&&t->next<BOOT_TRACE_ENTRIES&&t->pending_reason<=BOOT_REASON_BOOT_SELECTOR){
  view.sequence=t->sequence;view.count=t->count;view.pending_reason=t->pending_reason;
  unsigned oldest=(t->next+BOOT_TRACE_ENTRIES-t->count)%BOOT_TRACE_ENTRIES;
  for(unsigned i=0;i<t->count;i++)view.entries[i]=t->entries[(oldest+i)%BOOT_TRACE_ENTRIES];
  rc=0;
 }
 memcpy(out,&view,sizeof(view));return rc;
}
void boot_trace_encode(const struct boot_trace*t,uint8_t r[BOOT_TRACE_RECORD_SIZE])
{
 memset(r,0,BOOT_TRACE_RECORD_SIZE);put32(r,0x31544256u);r[4]=1;r[5]=t->count;r[6]=t->next;r[7]=t->pending_reason;put32(r+8,t->sequence);
 for(unsigned i=0;i<BOOT_TRACE_ENTRIES;i++){uint8_t*p=r+12+i*12;put32(p,t->entries[i].sequence);put32(p+4,t->entries[i].reset_flags);p[8]=t->entries[i].reason;p[9]=t->entries[i].image;}
 put32(r+84,crc32(r,84));
}
int boot_trace_decode(const uint8_t*r,size_t n,struct boot_trace*t)
{
 memset(t,0,sizeof(*t));
 if(!r||n!=BOOT_TRACE_RECORD_SIZE||get32(r)!=0x31544256u||r[4]!=1||r[5]>BOOT_TRACE_ENTRIES||r[6]>=BOOT_TRACE_ENTRIES||r[7]>BOOT_REASON_BOOT_SELECTOR||get32(r+84)!=crc32(r,84))return-EINVAL;
 for(unsigned i=0;i<BOOT_TRACE_ENTRIES;i++){const uint8_t*p=r+12+i*12;if(p[8]>BOOT_REASON_BOOT_SELECTOR||p[9]>BOOT_IMAGE_RECOVERY||p[10]||p[11])return-EINVAL;}
 t->count=r[5];t->next=r[6];t->pending_reason=r[7];t->sequence=get32(r+8);
 for(unsigned i=0;i<BOOT_TRACE_ENTRIES;i++){const uint8_t*p=r+12+i*12;t->entries[i]=(struct boot_trace_entry){.sequence=get32(p),.reset_flags=get32(p+4),.reason=p[8],.image=p[9]};}
 return 0;
}
