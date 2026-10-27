#include "vimar_buttons.h"
struct vimar_button_sample vimar_buttons_tick(struct vimar_buttons *b,uint64_t now,uint8_t raw)
{
 struct vimar_button_sample s={0};raw&=3;
 if(!b->initialized){b->initialized=true;b->blocked=true;b->raw=raw;b->raw_since=now;}
 if(raw!=b->raw){b->raw=raw;b->raw_since=now;}
 uint8_t previous=b->stable;
 if(now-b->raw_since>=30){b->stable=raw;}
 if(!b->enabled){
  if(raw==0&&b->stable==0&&now-b->raw_since>=30){b->enabled=true;b->blocked=false;}
  return s;
 }
 if(b->selecting){
  if(now-b->selector_since>=30000){b->selecting=false;b->chord=false;b->enabled=false;return s;}
  if(raw==3)b->selection_ready=false;
  if(raw==0&&b->stable==0&&now-b->raw_since>=30)b->selection_ready=true;
  if(b->selection_ready&&raw==b->stable&&(raw==1||raw==2)){
   s.pairing=raw==1;s.recovery=raw==2;b->selecting=false;b->chord=false;
  }
  return s;
 }
 if(raw==3){
  if(!b->blocked){s.cancel=true;b->blocked=true;}
  if(b->stable==3){
   if(!b->chord){b->chord=true;b->chord_since=now;b->sent=false;}
   if(!b->sent&&now-b->chord_since>=5000){
    s.selector=true;b->sent=true;b->selecting=true;
    b->selection_ready=false;b->selector_since=now;
   }
  }
 }else{b->chord=false;}
 if(b->blocked){if(raw==0&&b->stable==0&&now-b->raw_since>=30)b->blocked=false;return s;}
 s.changed=previous^b->stable;s.pressed=b->stable;return s;
}
