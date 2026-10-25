#include "research_buttons.h"
#include <assert.h>
#include <limits.h>
static struct research_buttons b;
static int32_t level;
static struct research_button_action tick(unsigned t, unsigned mask) {
 struct research_button_action a=research_buttons_tick(&b,t,mask,level);
 if(a.set_level) level=a.level;
 return a;
}
static void start(void) {research_buttons_init(&b);level=RESEARCH_LEVEL_OFF;tick(0,0);tick(40,0);}
static void press(unsigned t,unsigned mask){tick(t,mask);tick(t+40,mask);}
int main(void) {
 start(); press(100,1);assert(level==RESEARCH_LEVEL_OFF);press(200,0);assert(level==32767);
 press(300,2);press(400,0);assert(level==RESEARCH_LEVEL_OFF);
 level=1000;tick(500,0);press(600,1);press(700,0);assert(level==RESEARCH_LEVEL_OFF);
 press(800,2);press(900,0);assert(level==1000);
 /* Bounce never turns the lamp on. */
 start();tick(100,1);tick(110,0);tick(120,1);tick(130,0);tick(200,0);assert(level==RESEARCH_LEVEL_OFF);
 /* Long UP from OFF starts low, rises, stops on release without toggling. */
 start();press(100,1);tick(640,1);assert(level==RESEARCH_LEVEL_MIN);
 tick(690,1);assert(level>RESEARCH_LEVEL_MIN);int32_t before=level;
 press(700,0);assert(level==before);tick(2000,0);assert(level==before);
 /* A release at the long threshold must never become a short toggle,
  * including when that release arrives before the next held-key poll. */
 start();press(100,1);tick(640,0);tick(680,0);assert(level==RESEARCH_LEVEL_OFF);
 /* Long DOWN dims without switching off; endpoints clamp. */
 start();level=32767;press(100,2);tick(640,2);assert(level<32767);
 for(unsigned t=690;t<10000;t+=50)tick(t,2);
 assert(level==RESEARCH_LEVEL_MIN);press(10000,0);assert(level==RESEARCH_LEVEL_MIN);
 start();level=32760;press(100,1);tick(640,1);assert(level==32767);
 start();press(100,2);tick(640,2);press(700,0);assert(level==RESEARCH_LEVEL_OFF);
 /* Both cancels any gesture, suppresses release click and requests recovery once. */
 start();press(100,1);press(200,3);assert(level==RESEARCH_LEVEL_OFF);
 assert(!tick(5239,3).recovery);assert(tick(5240,3).recovery);assert(!tick(6000,3).recovery);
 press(6100,2);press(6200,0);assert(level==RESEARCH_LEVEL_OFF);
 start();level=10000;press(100,1);tick(640,1);before=level;press(700,3);tick(1000,3);assert(level==before);
 press(1100,1);press(1200,0);assert(level==before);
 /* A boot-held single key must be released before it may operate the lamp. */
 research_buttons_init(&b);level=RESEARCH_LEVEL_OFF;press(0,1);tick(1000,1);press(1100,0);assert(level==RESEARCH_LEVEL_OFF);
 press(1200,1);press(1300,0);assert(level==32767);
 /* BLE overrides cancel a pending local click or dim gesture. */
 start();press(100,1);research_buttons_cancel(&b);level=2000;press(200,0);assert(level==2000);
 /* Even an un-debounced second key suppresses the first key's click. */
 start();press(100,1);tick(200,3);tick(210,1);press(300,0);assert(level==RESEARCH_LEVEL_OFF);
 /* A remote override also cancels an active long gesture until release. */
 start();level=1000;press(100,1);tick(640,1);research_buttons_cancel(&b);
 level=5000;tick(1000,1);assert(level==5000);press(1100,0);assert(level==5000);
 /* A raw interruption restarts the continuous five-second recovery hold. */
 start();press(100,3);assert(!tick(5100,3).recovery);tick(5110,1);tick(5120,3);
 assert(!tick(5140,3).recovery);assert(!tick(10119,3).recovery);
 assert(tick(10120,3).recovery);assert(!tick(11000,3).recovery);
 /* Timing arithmetic must survive the 32-bit uptime wrap. */
 start();press(UINT_MAX-300,1);tick(240,1);assert(level==RESEARCH_LEVEL_MIN);
 return 0;
}
