/* SPDX-License-Identifier: Apache-2.0 */
#include "ota_split_stage.h"
#include "ota_stage.h"
#include <errno.h>
#include <string.h>
#include <stdbool.h>
int ota_split_validate(const struct ota_split_bounds*b)
{
 if(!b||b->start<OTA_PRIMARY_START||b->end!=OTA_STAGE_END||b->start>=b->end||
    b->start%4096||b->second_start!=OTA_SPLIT_SECOND_START||b->second_end!=OTA_SPLIT_SECOND_END||
    !b->payload_size||b->payload_size>(b->end-b->start)+(b->second_end-b->second_start))return-EINVAL;
 return 0;
}
int ota_split_plan(uint32_t current,uint32_t payload,uint32_t destination,uint32_t recovery,struct ota_split_bounds*out)
{
 if(!out||current<OTA_PRIMARY_START||current>OTA_STAGE_END||destination<OTA_PRIMARY_START||
    destination>OTA_STAGE_END||recovery<=OTA_PRIMARY_END||recovery>OTA_SPLIT_SECOND_START)return-EINVAL;
 uint32_t limit=current>destination?current:destination;
 uint32_t second=OTA_SPLIT_SECOND_END-OTA_SPLIT_SECOND_START;
 if(!payload||payload>OTA_STAGE_END-OTA_PRIMARY_START+second)return-EINVAL;
 uint32_t needed=payload>second?payload-second:(payload<4096?payload:4096);
 uint32_t start=(OTA_STAGE_END-needed)&~4095u;
 if(start<((limit+4095)&~4095u))return-ENOSPC;
 struct ota_split_bounds b={.start=start,.end=OTA_STAGE_END,
 .second_start=OTA_SPLIT_SECOND_START,.second_end=OTA_SPLIT_SECOND_END,.payload_size=payload};
 int rc=ota_split_validate(&b);if(!rc)*out=b;return rc;
}
int ota_split_map(const struct ota_split_bounds*b,uint32_t logical,uint32_t*physical,uint32_t*available)
{
 if(!physical||!available||ota_split_validate(b)||logical>=b->payload_size)return-EINVAL;
 uint32_t first=b->end-b->start,remaining=b->payload_size-logical,n;
 if(logical<first){*physical=b->start+logical;n=first-logical;}
 else{*physical=b->second_start+logical-first;n=b->second_end-*physical;}
 *available=n<remaining?n:remaining;return 0;
}

int ota_split_accept(struct ota_split_transfer*s,uint32_t off,const uint8_t*p,size_t n)
{
 if(!s||!p||!n||!s->read||!s->write||ota_split_validate(&s->bounds)||
 s->next_offset>s->bounds.payload_size||off>s->bounds.payload_size||n>s->bounds.payload_size-off)return-EINVAL;
 if(off>s->next_offset)return-EAGAIN;
 bool duplicate=off<s->next_offset;
 if(duplicate&&n>s->next_offset-off)return-EINVAL;
 uint32_t done=0;uint8_t compare[64];
 while(done<n){uint32_t physical,available;int rc=ota_split_map(&s->bounds,off+done,&physical,&available);if(rc)return rc;
  size_t count=n-done;if(count>available)count=available;
  if(duplicate){if(count>sizeof(compare))count=sizeof(compare);rc=s->read(s->context,physical,compare,count);
   if(rc)return rc<0?rc:-EIO;
   if(memcmp(compare,p+done,count))return-EILSEQ;
  }else{rc=s->write(s->context,physical,p+done,count);if(rc)return rc<0?rc:-EIO;}
  done+=count;
 }
 if(!duplicate)s->next_offset+=n;
 return 0;
}
