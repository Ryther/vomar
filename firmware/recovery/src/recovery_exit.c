#include "recovery_exit.h"
#include <string.h>
void recovery_exit_init(struct recovery_exit *s){memset(s,0,sizeof(*s));}
bool recovery_exit_tick(struct recovery_exit *s,uint32_t now,uint8_t pressed,bool inhibited)
{
 pressed&=3u;
 if(!s->initialized){s->initialized=true;s->raw=pressed;s->raw_since=now;}
 if(s->raw!=pressed){s->raw=pressed;s->raw_since=now;}
 bool debounced=(uint32_t)(now-s->raw_since)>=30;
 if(debounced)s->stable=s->raw;
 if(inhibited){s->ready=false;s->holding=false;s->qualified=false;return false;}
 if(!s->ready){
  if(!pressed&&!s->stable&&debounced)s->ready=true;
  return false;
 }
 if(s->qualified){
  if(!pressed&&!s->stable&&debounced){s->qualified=false;s->holding=false;return true;}
  return false;
 }
 if(pressed!=3u||s->stable!=3u){s->holding=false;return false;}
 if(!s->holding){s->holding=true;s->hold_since=now;}
 if((uint32_t)(now-s->hold_since)>=5000)s->qualified=true;
 return false;
}
