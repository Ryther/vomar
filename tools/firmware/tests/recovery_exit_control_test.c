#include <assert.h>
#include <errno.h>
#include <string.h>
#include "recovery_exit_control.h"
static int stored,valid,flush_error,clear_error,store_error,reboots;
static char order[64];static unsigned count;
static void op(char c){order[count++]=c;order[count]=0;}
static int persist(void *ctx,bool dirty){(void)ctx;op(dirty?'D':'C');if(store_error)return store_error;stored=dirty;return 0;}
static int verify(void *ctx){(void)ctx;op('V');return valid?0:-EACCES;}
static int flush(void *ctx){(void)ctx;op('F');return flush_error;}
static int clear(void *ctx){(void)ctx;op('B');return clear_error;}
static void reboot(void *ctx){(void)ctx;op('R');reboots++;}
static const struct recovery_exit_io io={.persist=persist,.verify=verify,.flush=flush,.clear_boot=clear,.reboot=reboot};
static void reset(void){stored=0;valid=1;flush_error=clear_error=store_error=reboots=0;count=0;order[0]=0;}
static int pairing_request(void){op('P');return store_error;}
int main(void)
{
 struct recovery_exit_control c;
 reset();recovery_exit_control_init(&c,0,0);
 /* Authorization during a valid existing image still requires an idle bus. */
 assert(!recovery_exit_command_begin(&c,false,&io));
 assert(recovery_exit_attempt(&c,&io)==-EBUSY&&reboots==0);
 recovery_exit_command_done(&c);
 assert(!recovery_exit_attempt(&c,&io));assert(!strcmp(order,"VFBR")&&reboots==1);
 assert(recovery_exit_attempt(&c,&io)==-EBUSY&&reboots==1);
 /* Durable partial intent precedes accepting upload/erase. A disconnect or
  * error never lets an unchanged-looking old signed prefix authorize exit. */
 reset();recovery_exit_control_init(&c,0,0);
 assert(!recovery_exit_command_begin(&c,true,&io)&&stored==1);
 recovery_exit_transfer_started(&c);recovery_exit_command_done(&c);
 assert(recovery_exit_attempt(&c,&io)==-EBUSY&&reboots==0);
 recovery_exit_transfer_stopped(&c);
 assert(recovery_exit_attempt(&c,&io)==-EBUSY&&reboots==0);
 struct recovery_exit_control after_power_loss;
 recovery_exit_control_init(&after_power_loss,1,(unsigned)stored);
 assert(recovery_exit_attempt(&after_power_loss,&io)==-EBUSY);
 /* An invalid/migrator/compressed candidate cannot clear the durable latch. */
 valid=0;
 assert(recovery_exit_transfer_complete(&c,&io)==-EACCES&&stored==1);
 assert(recovery_exit_attempt(&c,&io)==-EBUSY);
 valid=1;
 assert(!recovery_exit_transfer_complete(&c,&io)&&stored==0);
 assert(!recovery_exit_attempt(&c,&io)&&reboots==1);
 /* Every checkpoint failure keeps recovery, without reboot/bootmode clear. */
 reset();recovery_exit_control_init(&c,0,0);store_error=-EIO;
 assert(recovery_exit_command_begin(&c,true,&io)==-EIO&&reboots==0);
 recovery_exit_command_done(&c);assert(recovery_exit_attempt(&c,&io)==-EBUSY);
 reset();recovery_exit_control_init(&c,0,0);flush_error=-EIO;
 assert(recovery_exit_attempt(&c,&io)==-EIO&&!strcmp(order,"VF")&&reboots==0);
 reset();recovery_exit_control_init(&c,0,0);clear_error=-EIO;
 assert(recovery_exit_attempt(&c,&io)==-EIO&&!strcmp(order,"VFB")&&reboots==0);
 reset();recovery_exit_control_init(&c,0,0);valid=0;
 assert(recovery_exit_attempt(&c,&io)==-EACCES&&!strcmp(order,"V")&&reboots==0);
 /* Malformed or unreadable durable marker fails closed; a subsequent verified
  * completed transfer can recover the marker if storage becomes available. */
 reset();recovery_exit_control_init(&c,1,255);
 assert(recovery_exit_attempt(&c,&io)==-EBUSY);
 assert(!recovery_exit_command_begin(&c,true,&io)&&stored==1);
 recovery_exit_command_done(&c);assert(!recovery_exit_transfer_complete(&c,&io));
 assert(!recovery_exit_attempt(&c,&io));
 reset();recovery_exit_control_init(&c,-EIO,0);
 assert(recovery_exit_attempt(&c,&io)==-EBUSY);
 /* Pairing must own an admitted command, then wait for successful output. */
 reset();recovery_exit_control_init(&c,0,0);
 assert(recovery_exit_pairing_request(&c,&io)==-EBUSY);
 assert(!recovery_exit_command_begin(&c,false,&io));
 assert(!recovery_exit_pairing_request(&c,&io)&&c.exiting&&!c.pairing_ready);
 assert(recovery_exit_pairing_attempt(&c,&io,pairing_request)==-EBUSY&&reboots==0);
 recovery_exit_command_done(&c);recovery_exit_pairing_done(&c,false);
 assert(!c.exiting&&!c.pairing_pending&&reboots==0);
 assert(!recovery_exit_command_begin(&c,false,&io));
 assert(!recovery_exit_pairing_request(&c,&io));
 recovery_exit_command_done(&c);recovery_exit_pairing_done(&c,true);
 assert(c.pairing_ready);order[0]=0;count=0;
 assert(!recovery_exit_pairing_attempt(&c,&io,pairing_request));
 assert(!strcmp(order,"VFBPR")&&reboots==1);
 reset();recovery_exit_control_init(&c,1,1);
 assert(!recovery_exit_command_begin(&c,false,&io));
 assert(recovery_exit_pairing_request(&c,&io)==-EBUSY&&reboots==0);
 return 0;
}
