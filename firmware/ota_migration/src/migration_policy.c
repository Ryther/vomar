#include "migration_policy.h"
#include <errno.h>
static int no_set(void*c,uint8_t n){(void)c;(void)n;return 0;}
int migration_protection_preflight(int n,const struct research_handoff_io*io)
{
 if(n>0)return-EBUSY;
 if(n<0&&n!=-ENOENT)return n;
 uint8_t marker;int rc=io->get_marker(io->context,&marker);if(rc)return rc;
 if(!marker)return 0;
 if(marker==RESEARCH_HANDOFF_MARKER){
  struct research_handoff_io peek=*io;peek.set_marker=no_set;int32_t level;
  rc=research_handoff_take(&peek,&level);if(rc<0)return rc;
  if(rc!=1||level!=-32768)return-EPROTONOSUPPORT;
  return io->set_marker(io->context,0);
 }
 struct research_protected_handoff h;rc=research_handoff_peek_protected(io,&h);
 return rc==1?0:rc<0?rc:-EINVAL;
}
