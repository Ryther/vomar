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
 s=vimar_buttons_tick(&b,5440,3);assert(s.selector&&!s.recovery&&b.selecting);
 assert(!vimar_buttons_tick(&b,5500,3).selector);
 /* Releasing only one held key must not choose a mode. */
 vimar_buttons_tick(&b,5600,1);s=vimar_buttons_tick(&b,5640,1);assert(!s.changed);
 vimar_buttons_tick(&b,5700,0);s=vimar_buttons_tick(&b,5740,0);assert(!s.changed);
 vimar_buttons_tick(&b,5800,1);s=vimar_buttons_tick(&b,5840,1);
 assert(s.pairing&&!s.recovery&&!s.changed&&!b.selecting);
 assert(!vimar_buttons_tick(&b,5900,1).pairing);
 vimar_buttons_tick(&b,6000,0);vimar_buttons_tick(&b,6040,0);
 vimar_buttons_tick(&b,6100,3);vimar_buttons_tick(&b,6140,3);
 assert(vimar_buttons_tick(&b,11140,3).selector);
 vimar_buttons_tick(&b,11200,0);vimar_buttons_tick(&b,11240,0);
 vimar_buttons_tick(&b,11300,2);s=vimar_buttons_tick(&b,11340,2);
 assert(s.recovery&&!s.changed&&!s.pairing);
 /* Selector timeout never leaks a held key into lighting gestures. */
 vimar_buttons_tick(&b,11400,0);vimar_buttons_tick(&b,11440,0);
 vimar_buttons_tick(&b,11500,3);vimar_buttons_tick(&b,11540,3);
 assert(vimar_buttons_tick(&b,16540,3).selector);
 s=vimar_buttons_tick(&b,46540,1);assert(!b.selecting&&!s.changed&&!s.pairing);
 assert(!vimar_buttons_tick(&b,46580,1).changed);
 /* Boot-held key is ignored until every key is released. */
 b=(struct vimar_buttons){0};vimar_buttons_tick(&b,0,3);
 vimar_buttons_tick(&b,40,3);s=vimar_buttons_tick(&b,6000,3);assert(!s.selector&&!s.recovery);
 b=(struct vimar_buttons){0};vimar_buttons_tick(&b,0,1);assert(!vimar_buttons_tick(&b,1000,1).changed);
 vimar_buttons_tick(&b,1100,0);assert(!vimar_buttons_tick(&b,1140,0).changed);
 vimar_buttons_tick(&b,1200,2);s=vimar_buttons_tick(&b,1240,2);assert(s.changed==2&&s.pressed==2);
 /* A new chord must be fully released before a fresh single-key choice. */
 b=(struct vimar_buttons){0};vimar_buttons_tick(&b,0,0);vimar_buttons_tick(&b,40,0);
 vimar_buttons_tick(&b,100,3);vimar_buttons_tick(&b,140,3);assert(vimar_buttons_tick(&b,5140,3).selector);
 vimar_buttons_tick(&b,5200,0);vimar_buttons_tick(&b,5240,0);
 vimar_buttons_tick(&b,5300,3);vimar_buttons_tick(&b,5340,3);
 vimar_buttons_tick(&b,5400,1);s=vimar_buttons_tick(&b,5440,1);
 assert(!s.pairing&&!s.recovery&&b.selecting);
 /* Expiry cannot rearm the same continuously held chord. */
 s=vimar_buttons_tick(&b,35140,3);assert(!b.selecting&&!s.selector);
 s=vimar_buttons_tick(&b,40200,3);assert(!s.selector&&!b.selecting);
 s=vimar_buttons_tick(&b,45200,3);assert(!s.selector&&!b.selecting);
 return 0;
}
