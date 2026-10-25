#include "recovery_exit_control.h"
#include <assert.h>
#include <errno.h>
#include <string.h>
static int error,verify_error,flush_error,clear_error,reboots;
static char order[128];static unsigned n;
static void op(char c){order[n++]=c;order[n]=0;}
static int verify(void *ctx){(void)ctx;op('V');return verify_error;}
static int flush(void *ctx){(void)ctx;op('F');return flush_error;}
static int clear(void *ctx){(void)ctx;op('B');return clear_error;}
static void reboot(void *ctx){(void)ctx;op('R');reboots++;}
static int persist(void *ctx,bool dirty){(void)ctx;(void)dirty;return 0;}
static const struct recovery_exit_io io={.persist=persist,.verify=verify,.flush=flush,.clear_boot=clear,.reboot=reboot};
static void reset(struct recovery_exit_control *c)
{recovery_exit_control_init(c,0,0);error=verify_error=flush_error=clear_error=reboots=0;n=0;order[0]=0;}
int main(void)
{
 struct recovery_exit_control c;
 reset(&c);
 assert(recovery_exit_migration_request(&c,&io)==-EBUSY); /* Must own admitted command. */
 assert(!recovery_exit_command_begin(&c,false,&io));
 assert(!recovery_exit_migration_request(&c,&io)&&!strcmp(order,"VF"));
 assert(c.exiting&&c.migration_pending&&!c.migration_ready&&!reboots);
 assert(recovery_exit_command_begin(&c,true,&io)==-EBUSY);
 assert(recovery_exit_attempt(&c,&io)==-EBUSY);
 assert(recovery_exit_migration_attempt(&c,&io)==-EBUSY&&!reboots);
 recovery_exit_command_done(&c);recovery_exit_migration_done(&c,true);
 assert(c.migration_ready);
 assert(!recovery_exit_migration_attempt(&c,&io)&&!strcmp(order,"VFVFBR")&&reboots==1);
 /* Every earlier gate and callback failure refuses without transition. */
 for(unsigned kind=0;kind<4;kind++){
  reset(&c);assert(!recovery_exit_command_begin(&c,false,&io));
  if(kind==0)c.partial=true;
  if(kind==1)c.session=true;
  if(kind==2)verify_error=-EACCES;
  if(kind==3)flush_error=-EIO;
  assert(recovery_exit_migration_request(&c,&io)<0&&!c.exiting&&!reboots);
 }
 /* Failed output or disconnect cancels only RPC ownership. */
 for(unsigned kind=0;kind<2;kind++){
  reset(&c);assert(!recovery_exit_command_begin(&c,false,&io));
  assert(!recovery_exit_migration_request(&c,&io));recovery_exit_command_done(&c);
  if(kind==0)recovery_exit_migration_done(&c,false);else recovery_exit_migration_cancel(&c);
  assert(!c.exiting&&!c.migration_pending&&!c.migration_ready);
  assert(recovery_exit_migration_attempt(&c,&io)==-EBUSY&&!reboots);
  assert(!recovery_exit_command_begin(&c,true,&io));
 }
 /* Successful response is not execution authority if primary/checkpoint changed. */
 for(unsigned kind=0;kind<3;kind++){
  reset(&c);assert(!recovery_exit_command_begin(&c,false,&io));
  assert(!recovery_exit_migration_request(&c,&io));recovery_exit_command_done(&c);
  recovery_exit_migration_done(&c,true);
  if(kind==0)verify_error=-EACCES;
  if(kind==1)flush_error=-EIO;
  if(kind==2)clear_error=-EIO;
  assert(recovery_exit_migration_attempt(&c,&io)<0&&!reboots&&!c.exiting&&!c.migration_pending);
 }
 /* SDK reset is already scheduled after its hook: RPC errors/disconnect must
  * never reopen the mutation fence for that independently owned transition. */
 reset(&c);assert(!recovery_exit_command_begin(&c,false,&io));
 assert(!recovery_exit_sdk_reset_prepare(&c,&io)&&!strcmp(order,"VFB"));
 assert(c.exiting&&!c.migration_pending);
 recovery_exit_command_done(&c);recovery_exit_migration_done(&c,false);recovery_exit_migration_cancel(&c);
 assert(c.exiting&&recovery_exit_command_begin(&c,true,&io)==-EBUSY&&!reboots);
 return error;
}
