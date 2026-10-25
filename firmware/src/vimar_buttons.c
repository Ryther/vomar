#include "vimar_buttons.h"
struct vimar_button_sample vimar_buttons_tick(struct vimar_buttons *b,uint64_t now,uint8_t raw)
{
 struct vimar_button_sample s={0};raw&=3;
 if(!b->initialized){b->initialized=true;b->blocked=true;b->raw=raw;b->raw_since=now;}
 if(raw!=b->raw){b->raw=raw;b->raw_since=now;}
 uint8_t previous=b->stable;
 if(now-b->raw_since>=30){b->stable=raw;}
 if(raw==3){
  if(!b->blocked){s.cancel=true;b->blocked=true;}
  if(b->stable==3){
   if(!b->chord){b->chord=true;b->chord_since=now;b->sent=false;}
   if(!b->sent&&now-b->chord_since>=5000){s.recovery=true;b->sent=true;}
  }
 }else{b->chord=false;}
 if(b->blocked){if(raw==0&&b->stable==0&&now-b->raw_since>=30)b->blocked=false;return s;}
 s.changed=previous^b->stable;s.pressed=b->stable;return s;
}
