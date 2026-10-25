#include "research_handoff.h"
#include <errno.h>
#define HANDOFF_MAGIC 0x31534856u
static void put32(uint8_t *p, uint32_t n)
{
    for (unsigned i=0; i<4; ++i) { p[i]=(uint8_t)(n>>(8*i)); }
}
static uint32_t get32(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24;
}
int research_handoff_prepare(const struct research_handoff_io *io, int32_t level)
{
    if (level < -32768 || level > 32767) { return -EINVAL; }
    uint8_t record[RESEARCH_HANDOFF_SIZE];
    put32(record, HANDOFF_MAGIC);
    put32(record+4, (uint32_t)level);
    put32(record+8, ~((uint32_t)level ^ HANDOFF_MAGIC));
    /* A failed new save cannot authorize replaying the previous flash record. */
    int result=io->set_marker(io->context, 0);
    if (result != 0) { return result; }
    result=io->save(io->context, record, sizeof(record));
    if (result != 0) { return result; }
    return io->set_marker(io->context, RESEARCH_HANDOFF_MARKER);
}
int research_handoff_take(const struct research_handoff_io *io, int32_t *level)
{
    *level=-32768;
    uint8_t marker;
    int result=io->get_marker(io->context, &marker);
    if (result != 0) { return result; }
    if (marker != RESEARCH_HANDOFF_MARKER) { return 0; }
    /* Consume first, even if reading/validating the saved record later fails. */
    result=io->set_marker(io->context, 0);
    if (result != 0) { return result; }
    uint8_t record[RESEARCH_HANDOFF_SIZE];
    result=io->load(io->context, record, sizeof(record));
    if (result != 0) { return result; }
    uint32_t raw=get32(record+4);
    int64_t decoded=raw <= INT32_MAX ? (int64_t)raw : (int64_t)raw-4294967296LL;
    if (get32(record)!=HANDOFF_MAGIC || get32(record+8)!=~(raw ^ HANDOFF_MAGIC) ||
        decoded < -32768 || decoded > 32767) { return -EINVAL; }
    *level=(int32_t)decoded;
    return 1;
}

/* Separate marker/magic make the new record unambiguously incompatible with
 * legacy ON authorizations. Legacy functions remain for frozen restore paths. */
static uint32_t handoff_crc(const uint8_t *p,size_t n)
{
 uint32_t crc=UINT32_MAX;
 for(size_t i=0;i<n;i++){crc^=p[i];for(unsigned bit=0;bit<8;bit++)crc=(crc>>1)^((crc&1)?0xedb88320u:0u);}
 return ~crc;
}
int research_handoff_prepare_protected(const struct research_handoff_io *io,const struct research_protected_handoff *h)
{
 if(h->level < -32768 || h->level>32767)return-EINVAL;
 uint8_t record[RESEARCH_PROTECTED_HANDOFF_SIZE];
 put32(record,0x32534856u);put32(record+4,(uint32_t)(h->inhibited?-32768:h->level));
 put32(record+8,h->trips);put32(record+12,(h->armed?1u:0u)|(h->inhibited?2u:0u));
 put32(record+16,handoff_crc(record,16));
 int rc=io->set_marker(io->context,0);if(rc)return rc;
 rc=io->save(io->context,record,sizeof(record));if(rc)return rc;
 return io->set_marker(io->context,RESEARCH_PROTECTED_HANDOFF_MARKER);
}
static int protected_read(const struct research_handoff_io *io,struct research_protected_handoff *h,bool consume)
{
 *h=(struct research_protected_handoff){.level=-32768,.inhibited=true};
 uint8_t marker;int rc=io->get_marker(io->context,&marker);if(rc)return rc;
 if(marker!=RESEARCH_PROTECTED_HANDOFF_MARKER){
  if(marker){
   if(consume){rc=io->set_marker(io->context,0);if(rc)return rc;}
   return marker==RESEARCH_HANDOFF_MARKER?-EPROTONOSUPPORT:-EINVAL;
  }
  return 0;
 }
 if(consume){rc=io->set_marker(io->context,0);if(rc)return rc;}
 uint8_t record[RESEARCH_PROTECTED_HANDOFF_SIZE];rc=io->load(io->context,record,sizeof(record));if(rc)return rc;
 uint32_t raw=get32(record+4),flags=get32(record+12);
 int64_t level=raw<=INT32_MAX?(int64_t)raw:(int64_t)raw-4294967296LL;
 if(get32(record)!=0x32534856u||get32(record+16)!=handoff_crc(record,16)||
    (flags&~3u)||level < -32768 || level>32767 || ((flags&2)&&level!=-32768))return-EINVAL;
 *h=(struct research_protected_handoff){.level=(int32_t)level,.trips=get32(record+8),.armed=(flags&1)!=0,.inhibited=(flags&2)!=0};
 return 1;
}
int research_handoff_take_protected(const struct research_handoff_io *io,struct research_protected_handoff *h)
{return protected_read(io,h,true);}
int research_handoff_peek_protected(const struct research_handoff_io *io,struct research_protected_handoff *h)
{return protected_read(io,h,false);}
