#include "research_handoff.h"
#include <assert.h>
#include <errno.h>
#include <string.h>
struct memory { unsigned char record[12], marker; int saves, loads, fail_save, fail_load, fail_marker, short_load; };
static int load(void *v,unsigned char *p,size_t n){struct memory*m=v;m->loads++;if(m->fail_load)return-EIO;memcpy(p,m->record,n);return m->short_load?-EINVAL:0;}
static int save(void*v,const unsigned char*p,size_t n){struct memory*m=v;m->saves++;if(m->fail_save)return-EIO;memcpy(m->record,p,n);return 0;}
static int get(void*v,unsigned char*p){*p=((struct memory*)v)->marker;return 0;}
static int set(void*v,unsigned char p){struct memory*m=v;if(m->fail_marker)return-EIO;m->marker=p;return 0;}
int main(void){
 struct memory m={0};struct research_handoff_io io={.context=&m,.load=load,.save=save,.get_marker=get,.set_marker=set};int32_t level;
 /* No marker: cold/default boot stays OFF even if old flash state exists. */
 assert(research_handoff_take(&io,&level)==0&&level==-32768&&m.loads==0);
 int32_t levels[]={-32768,-30000,-16384,0,12345,32767};
 for(unsigned i=0;i<sizeof(levels)/sizeof(levels[0]);i++){
  assert(research_handoff_prepare(&io,levels[i])==0&&m.marker!=0);
  assert(research_handoff_take(&io,&level)==1&&level==levels[i]&&m.marker==0);
  assert(research_handoff_take(&io,&level)==0&&level==-32768);
 }
 /* Invalid/corrupt records never energize an output and are consumed once. */
 assert(research_handoff_prepare(&io,1000)==0);m.record[4]^=1;
 assert(research_handoff_take(&io,&level)==-EINVAL&&level==-32768&&m.marker==0);
 assert(research_handoff_prepare(&io,1000)==0);m.record[0]^=1;
 assert(research_handoff_take(&io,&level)==-EINVAL&&level==-32768);
 m.short_load=1;assert(research_handoff_prepare(&io,1000)==0);
 assert(research_handoff_take(&io,&level)<0&&level==-32768);m.short_load=0;
 assert(research_handoff_prepare(&io,32768)==-EINVAL);assert(research_handoff_prepare(&io,-32769)==-EINVAL);
 /* Persistence must succeed before the retained authorization marker is armed. */
 m.fail_save=1;assert(research_handoff_prepare(&io,1000)==-EIO&&m.marker==0);m.fail_save=0;
 assert(research_handoff_prepare(&io,1000)==0);m.fail_load=1;
 assert(research_handoff_take(&io,&level)==-EIO&&level==-32768&&m.marker==0);m.fail_load=0;
 /* Marker I/O failure must not restore or save a stale level. */
 m.fail_marker=1;int saved=m.saves;
 assert(research_handoff_prepare(&io,1000)==-EIO&&m.saves==saved);
 m.marker=RESEARCH_HANDOFF_MARKER;assert(research_handoff_take(&io,&level)==-EIO&&level==-32768);
 return 0;
}
