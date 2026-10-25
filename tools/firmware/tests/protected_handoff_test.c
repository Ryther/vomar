#include "research_handoff.h"
#include <assert.h>
#include <errno.h>
#include <string.h>
struct memory {unsigned char record[RESEARCH_PROTECTED_HANDOFF_SIZE],marker;int fail_save,fail_load;};
static int load(void*v,unsigned char*p,size_t n){struct memory*m=v;if(m->fail_load)return-EIO;memcpy(p,m->record,n);return 0;}
static int save(void*v,const unsigned char*p,size_t n){struct memory*m=v;if(m->fail_save)return-EIO;memcpy(m->record,p,n);return 0;}
static int get(void*v,unsigned char*p){*p=((struct memory*)v)->marker;return 0;}
static int set(void*v,unsigned char x){((struct memory*)v)->marker=x;return 0;}
int main(void){
 struct memory m={0};struct research_handoff_io io={.context=&m,.load=load,.save=save,.get_marker=get,.set_marker=set};
 struct research_protected_handoff in={.level=12345,.trips=17,.armed=true},out;
 assert(research_handoff_prepare_protected(&io,&in)==0);
 assert(m.marker==RESEARCH_PROTECTED_HANDOFF_MARKER);
 assert(research_handoff_peek_protected(&io,&out)==1&&out.level==12345&&out.armed&&out.trips==17&&m.marker!=0);
 int32_t legacy=123;assert(research_handoff_take(&io,&legacy)==0&&legacy==-32768);
 assert(research_handoff_take_protected(&io,&out)==1&&out.level==12345&&m.marker==0);
 assert(research_handoff_take_protected(&io,&out)==0&&out.level==-32768);
 in.inhibited=true;assert(research_handoff_prepare_protected(&io,&in)==0);
 assert(research_handoff_take_protected(&io,&out)==1&&out.inhibited&&out.level==-32768);
 in.inhibited=false;
 for(unsigned i=0;i<RESEARCH_PROTECTED_HANDOFF_SIZE;i++){
  assert(research_handoff_prepare_protected(&io,&in)==0);m.record[i]^=1;
  assert(research_handoff_take_protected(&io,&out)<0&&out.level==-32768&&m.marker==0);
 }
 assert(research_handoff_prepare(&io,12345)==0);
 assert(research_handoff_take_protected(&io,&out)==-EPROTONOSUPPORT&&out.level==-32768&&m.marker==0);
 m.marker=0xa9;assert(research_handoff_take_protected(&io,&out)==-EINVAL&&out.level==-32768&&m.marker==0);
 m.fail_save=1;assert(research_handoff_prepare_protected(&io,&in)==-EIO&&m.marker==0);m.fail_save=0;
 assert(research_handoff_prepare_protected(&io,&in)==0);m.fail_load=1;
 assert(research_handoff_take_protected(&io,&out)==-EIO&&out.level==-32768&&m.marker==0);
 return 0;
}
