#include "candidate_power_protection.h"
#include <errno.h>
#include <limits.h>
#include <string.h>

void candidate_power_protection_init(struct candidate_power_protection *s,const struct candidate_protection_record *r)
{
 memset(s,0,sizeof(*s));
 if(r){s->inhibit=r->inhibit;s->input_fault=r->input_fault;s->notification=r->notification;s->trips=r->trips;}
}
bool candidate_power_protection_blocked(const struct candidate_power_protection *s)
{return !s->raw_valid||s->inhibit||s->input_fault;}
void candidate_power_protection_acknowledge(struct candidate_power_protection *s)
{if(!candidate_power_protection_blocked(s))s->notification=false;}
unsigned candidate_power_protection_sample(struct candidate_power_protection *s,uint64_t now,int raw)
{
 unsigned events=0;
 if(!s->have_sample)s->first_sample_ms=now;
 if(s->have_sample){
  uint64_t gap=now-s->last_sample_ms;
  if(gap>s->max_gap_ms)s->max_gap_ms=gap>UINT32_MAX?UINT32_MAX:(uint32_t)gap;
  if(now<s->last_sample_ms||gap>CANDIDATE_PROTECTION_MAX_GAP_MS){
   s->raw_valid=s->stable_valid=s->low_qualified=false;s->input_fault=true;s->notification=true;
   events|=CANDIDATE_PROTECTION_GAP;
  }
 }
 s->have_sample=true;s->last_sample_ms=now;
 if(raw!=0&&raw!=1){
  s->raw_valid=s->stable_valid=s->low_qualified=false;s->input_fault=true;s->notification=true;
  return events|CANDIDATE_PROTECTION_INVALID;
 }
 bool high=raw!=0;
 if(!s->raw_valid||s->raw_high!=high){s->raw_high=high;s->raw_since_ms=now;}
 s->raw_valid=true;
 if(now-s->raw_since_ms<CANDIDATE_PROTECTION_DEBOUNCE_MS)return events;
 if(!s->stable_valid||s->stable_high!=high){
  s->stable_valid=true;s->stable_high=high;s->stable_since_ms=now;
  if(high&&s->low_qualified){
   s->low_qualified=false;s->inhibit=true;s->notification=true;
   if(s->trips<UINT32_MAX)s->trips++;
   events|=CANDIDATE_PROTECTION_TRIP;
  }
 }
 if(!high&&!s->low_qualified&&now-s->stable_since_ms>=CANDIDATE_PROTECTION_LOW_MS){
  s->low_qualified=true;
  if(s->inhibit||s->input_fault)events|=CANDIDATE_PROTECTION_CLEAR;
  s->inhibit=s->input_fault=false;
 }
 return events;
}
static void put32(uint8_t *p,uint32_t n){for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(n>>(8*i));}
static uint32_t get32(const uint8_t *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static uint32_t crc32(const uint8_t *p,size_t n)
{
 uint32_t crc=UINT32_MAX;
 for(size_t i=0;i<n;i++){crc^=p[i];for(unsigned bit=0;bit<8;bit++)crc=(crc>>1)^((crc&1)?0xedb88320u:0u);}
 return ~crc;
}
void candidate_power_protection_encode(const struct candidate_power_protection *s,uint8_t record[CANDIDATE_PROTECTION_RECORD_SIZE])
{
 memset(record,0,CANDIDATE_PROTECTION_RECORD_SIZE);put32(record,0x53313350u);
 record[4]=1;record[5]=(s->inhibit?1:0)|(s->input_fault?2:0)|(s->notification?4:0);
 put32(record+8,s->trips);put32(record+12,crc32(record,12));
}
int candidate_power_protection_decode(const uint8_t *p,size_t n,struct candidate_protection_record *r)
{
 *r=(struct candidate_protection_record){.inhibit=true,.input_fault=true,.notification=true};
 if(!p||n!=CANDIDATE_PROTECTION_RECORD_SIZE||get32(p)!=0x53313350u||p[4]!=1||
    (p[5]&~7u)||p[6]||p[7]||get32(p+12)!=crc32(p,12))return-EINVAL;
 *r=(struct candidate_protection_record){.inhibit=(p[5]&1)!=0,.input_fault=(p[5]&2)!=0,
     .notification=(p[5]&4)!=0,.trips=get32(p+8)};
 return 0;
}
