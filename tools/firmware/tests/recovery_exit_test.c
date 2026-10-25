#include <assert.h>
#include <stdint.h>
#include "recovery_exit.h"
int main(void)
{
 struct recovery_exit s;
 recovery_exit_init(&s);
 /* Stuck buttons at boot never authorize an exit, even after a long hold. */
 assert(!recovery_exit_tick(&s,0,3,false));
 assert(!recovery_exit_tick(&s,10000,3,false));
 assert(!recovery_exit_tick(&s,10001,1,false));
 assert(!recovery_exit_tick(&s,20000,1,false));
 assert(!recovery_exit_tick(&s,20001,0,false));
 assert(!recovery_exit_tick(&s,20031,0,false));
 assert(!recovery_exit_tick(&s,20032,3,false));
 assert(!recovery_exit_tick(&s,20062,3,false));
 assert(!recovery_exit_tick(&s,25061,3,false));
 assert(!recovery_exit_tick(&s,25062,3,false)); /* Qualified, wait release. */
 assert(!recovery_exit_tick(&s,26000,1,false));
 assert(!recovery_exit_tick(&s,26030,1,false));
 assert(!recovery_exit_tick(&s,26031,0,false));
 assert(recovery_exit_tick(&s,26061,0,false));
 assert(!recovery_exit_tick(&s,30000,0,false)); /* One exit per hold. */
 /* Short holds, raw interruptions and bounce cannot accumulate five seconds. */
 recovery_exit_init(&s);
 recovery_exit_tick(&s,0,0,false);recovery_exit_tick(&s,30,0,false);
 recovery_exit_tick(&s,31,3,false);recovery_exit_tick(&s,61,3,false);
 recovery_exit_tick(&s,5000,1,false);recovery_exit_tick(&s,5001,3,false);
 assert(!recovery_exit_tick(&s,5061,3,false));
 recovery_exit_tick(&s,5062,0,false);
 assert(!recovery_exit_tick(&s,5092,0,false));
 /* An upload/partial image cancels the current gesture, including a qualified
  * hold released while busy. The user must release and make a new hold. */
 recovery_exit_tick(&s,6000,3,false);recovery_exit_tick(&s,6030,3,false);
 recovery_exit_tick(&s,11030,3,false);
 recovery_exit_tick(&s,11031,3,true);
 recovery_exit_tick(&s,11032,0,true);
 assert(!recovery_exit_tick(&s,11062,0,true));
 assert(!recovery_exit_tick(&s,11063,0,false));
 recovery_exit_tick(&s,12000,3,false);recovery_exit_tick(&s,12030,3,false);
 recovery_exit_tick(&s,17030,3,false);recovery_exit_tick(&s,17031,0,false);
 assert(recovery_exit_tick(&s,17061,0,false));
 /* Unsigned uptime subtraction supports a wrap during the hold. */
 recovery_exit_init(&s);
 recovery_exit_tick(&s,UINT32_MAX-100,0,false);
 recovery_exit_tick(&s,UINT32_MAX-70,0,false);
 recovery_exit_tick(&s,UINT32_MAX-60,3,false);
 recovery_exit_tick(&s,UINT32_MAX-30,3,false);
 recovery_exit_tick(&s,4969,3,false);recovery_exit_tick(&s,4970,0,false);
 assert(recovery_exit_tick(&s,5000,0,false));
 return 0;
}
