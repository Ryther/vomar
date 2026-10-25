#include "vimar_buttons.h"
#include <assert.h>
int main(void){
 struct vimar_buttons b={0};struct vimar_button_sample s;
 vimar_buttons_tick(&b,0,0);vimar_buttons_tick(&b,40,0);
 vimar_buttons_tick(&b,100,1);s=vimar_buttons_tick(&b,140,1);assert(s.changed==1&&s.pressed==1);
 vimar_buttons_tick(&b,200,0);s=vimar_buttons_tick(&b,240,0);assert(s.changed==1&&s.pressed==0);
 vimar_buttons_tick(&b,300,1);vimar_buttons_tick(&b,340,1);
 s=vimar_buttons_tick(&b,400,3);assert(s.cancel);
 vimar_buttons_tick(&b,440,3);assert(!vimar_buttons_tick(&b,5439,3).recovery);
 assert(vimar_buttons_tick(&b,5440,3).recovery);assert(!vimar_buttons_tick(&b,5500,3).recovery);
 vimar_buttons_tick(&b,5600,1);s=vimar_buttons_tick(&b,5640,1);assert(!s.changed);
 vimar_buttons_tick(&b,5700,0);s=vimar_buttons_tick(&b,5740,0);assert(!s.changed);
 /* Boot-held key is ignored until every key is released. */
 b=(struct vimar_buttons){0};vimar_buttons_tick(&b,0,1);assert(!vimar_buttons_tick(&b,1000,1).changed);
 vimar_buttons_tick(&b,1100,0);assert(!vimar_buttons_tick(&b,1140,0).changed);
 vimar_buttons_tick(&b,1200,2);s=vimar_buttons_tick(&b,1240,2);assert(s.changed==2&&s.pressed==2);
 return 0;
}
