#include "candidate_power_protection.h"
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <string.h>

static void run(struct candidate_power_protection *s,uint64_t from,uint64_t to,int raw)
{for(uint64_t now=from;now<=to;now+=10)candidate_power_protection_sample(s,now,raw);}
static void qualify(struct candidate_power_protection *s,uint64_t now)
{run(s,now,now+580,0);assert(s->low_qualified&&!candidate_power_protection_blocked(s));}
int main(void)
{
 struct candidate_power_protection s;
 candidate_power_protection_init(&s,0);
 assert(candidate_power_protection_blocked(&s));
 run(&s,0,1000,1);assert(!s.inhibit&&!s.low_qualified&&!candidate_power_protection_blocked(&s));
 /* Short LOW and a bouncing release cannot manufacture a long assertion. */
 run(&s,1010,1200,0);run(&s,1210,1400,1);assert(!s.inhibit);
 qualify(&s,1410);assert(!s.inhibit);
 run(&s,2000,2070,1);assert(!s.inhibit);
 unsigned e=candidate_power_protection_sample(&s,2080,1);
 assert((e&CANDIDATE_PROTECTION_TRIP)&&s.inhibit&&s.notification&&s.trips==1);
 run(&s,2090,2300,1);assert(s.trips==1);
 qualify(&s,2310);assert(!s.inhibit&&s.notification);
 candidate_power_protection_acknowledge(&s);assert(!s.notification);
 /* Invalid samples block at once; repeated HIGH cannot acknowledge them. */
 e=candidate_power_protection_sample(&s,2900,-EIO);assert(e&CANDIDATE_PROTECTION_INVALID);
 assert(candidate_power_protection_blocked(&s)&&s.notification);
 run(&s,2910,3200,1);assert(candidate_power_protection_blocked(&s));
 qualify(&s,3210);assert(!s.input_fault);
 /* A sampling gap cannot count an unseen LOW interval toward qualification. */
 candidate_power_protection_init(&s,0);run(&s,0,100,0);
 e=candidate_power_protection_sample(&s,1000,0);
 assert(e&CANDIDATE_PROTECTION_GAP);assert(!s.low_qualified&&candidate_power_protection_blocked(&s)&&s.notification);
 run(&s,1010,1570,0);assert(candidate_power_protection_blocked(&s));
 candidate_power_protection_sample(&s,1580,0);assert(!candidate_power_protection_blocked(&s));
 assert(s.max_gap_ms==900);
 candidate_power_protection_sample(&s,1500,0);assert(candidate_power_protection_blocked(&s));
 /* Qualified release and counter saturation across uint32 uptime boundary. */
 candidate_power_protection_init(&s,0);uint64_t start=UINT32_MAX-300ULL;qualify(&s,start);
 s.trips=UINT32_MAX;run(&s,start+590,start+670,1);assert(s.inhibit&&s.trips==UINT32_MAX);
 /* The persistent codec is bounded, versioned and detects every single bit corruption. */
 uint8_t record[CANDIDATE_PROTECTION_RECORD_SIZE],bad[CANDIDATE_PROTECTION_RECORD_SIZE];
 struct candidate_protection_record decoded;
 candidate_power_protection_encode(&s,record);
 assert(candidate_power_protection_decode(record,sizeof(record),&decoded)==0);
 assert(decoded.inhibit&&decoded.notification&&decoded.trips==UINT32_MAX);
 for(unsigned i=0;i<sizeof(record);i++)for(unsigned bit=0;bit<8;bit++){
  memcpy(bad,record,sizeof(bad));bad[i]^=1U<<bit;
  assert(candidate_power_protection_decode(bad,sizeof(bad),&decoded)<0);
  assert(decoded.inhibit&&decoded.input_fault);
 }
 assert(candidate_power_protection_decode(record,sizeof(record)-1,&decoded)<0);
 assert(candidate_power_protection_decode(NULL,0,&decoded)<0);
 /* Cold boot restores inhibit, never a previous LOW qualification. */
 assert(candidate_power_protection_decode(record,sizeof(record),&decoded)==0);
 candidate_power_protection_init(&s,&decoded);run(&s,0,1000,1);
 assert(candidate_power_protection_blocked(&s)&&!s.low_qualified);
 qualify(&s,1010);assert(!s.inhibit);
 return 0;
}
