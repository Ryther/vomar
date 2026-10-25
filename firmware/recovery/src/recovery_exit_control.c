#include "recovery_exit_control.h"
#include <errno.h>
#include <string.h>
void recovery_exit_control_init(struct recovery_exit_control *c,ssize_t length,unsigned value)
{
 memset(c,0,sizeof(*c));
 c->partial=length!=0;
 c->durable=length==1&&value==1;
}
int recovery_exit_command_begin(struct recovery_exit_control *c,bool write,const struct recovery_exit_io *io)
{
 if(c->exiting||c->command_busy)return-EBUSY;
 if(write){
  c->partial=true;
  if(!c->durable){
   int rc=io->persist(io->context,true);
   if(rc)return rc;
   c->durable=true;
  }
 }
 /* Publication of command ownership follows successful durable admission.
  * Failed persistence still latches partial, but must not strand diagnostics
  * behind an owner that the adapter never admitted. */
 c->command_busy=true;
 return 0;
}
void recovery_exit_command_done(struct recovery_exit_control *c){c->command_busy=false;}
void recovery_exit_transfer_started(struct recovery_exit_control *c){c->session=true;}
void recovery_exit_transfer_stopped(struct recovery_exit_control *c){c->session=false;}
int recovery_exit_transfer_complete(struct recovery_exit_control *c,const struct recovery_exit_io *io)
{
 c->session=false;
 c->partial=true;
 int rc=io->verify(io->context);
 if(!rc)rc=io->persist(io->context,false);
 if(rc)return rc;
 c->partial=false;c->durable=false;
 return 0;
}
int recovery_exit_attempt(struct recovery_exit_control *c,const struct recovery_exit_io *io)
{
 if(c->partial||c->session||c->command_busy||c->exiting)return-EBUSY;
 int rc=io->verify(io->context);
 if(!rc)rc=io->flush(io->context);
 if(!rc)rc=io->clear_boot(io->context);
 if(rc)return rc;
 c->exiting=true;
 io->reboot(io->context);
 return 0;
}
int recovery_exit_migration_request(struct recovery_exit_control *c,const struct recovery_exit_io *io)
{
 if(!c->command_busy||c->partial||c->session||c->exiting)return-EBUSY;
 int rc=io->verify(io->context);
 if(!rc)rc=io->flush(io->context);
 if(rc)return rc;
 c->exiting=true;c->migration_pending=true;c->migration_ready=false;
 return 0;
}
void recovery_exit_migration_cancel(struct recovery_exit_control *c)
{
 if(!c->migration_pending)return;
 c->migration_pending=false;c->migration_ready=false;c->exiting=false;
}
void recovery_exit_migration_done(struct recovery_exit_control *c,bool output_ok)
{
 if(!c->migration_pending)return;
 if(!output_ok||c->command_busy)recovery_exit_migration_cancel(c);
 else c->migration_ready=true;
}
int recovery_exit_migration_attempt(struct recovery_exit_control *c,const struct recovery_exit_io *io)
{
 if(!c->migration_pending||!c->migration_ready||!c->exiting||c->partial||c->session||c->command_busy)return-EBUSY;
 int rc=io->verify(io->context);
 if(!rc)rc=io->flush(io->context);
 if(!rc)rc=io->clear_boot(io->context);
 if(rc){recovery_exit_migration_cancel(c);return rc;}
 io->reboot(io->context);
 return 0;
}
int recovery_exit_sdk_reset_prepare(struct recovery_exit_control *c,const struct recovery_exit_io *io)
{
 if(!c->command_busy||c->partial||c->session||c->exiting)return-EBUSY;
 int rc=io->verify(io->context);
 if(!rc)rc=io->flush(io->context);
 if(!rc)rc=io->clear_boot(io->context);
 if(rc)return rc;
 /* The SDK may schedule its reset as soon as this returns. Never thaw this
  * fence on command output error or disconnect; only a reboot releases it. */
 c->exiting=true;
 return 0;
}
