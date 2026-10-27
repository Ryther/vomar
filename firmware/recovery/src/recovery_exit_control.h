#ifndef VIMAR_RECOVERY_EXIT_CONTROL_H
#define VIMAR_RECOVERY_EXIT_CONTROL_H
#include <stdbool.h>
#include <sys/types.h>
/* Caller serializes every operation against SMP command admission and image IO. */
struct recovery_exit_control {
 bool partial,durable,session,command_busy,exiting;
 /* exiting without migration_pending belongs to the SDK/ordinary exit and
  * must never be cancelled by RPC output errors or disconnect. */
 bool migration_pending,migration_ready;
 bool pairing_pending,pairing_ready;
};
struct recovery_exit_io {
 void *context;
 int (*persist)(void *,bool);
 int (*verify)(void *);
 int (*flush)(void *);
 int (*clear_boot)(void *);
 void (*reboot)(void *);
};
void recovery_exit_control_init(struct recovery_exit_control *,ssize_t,unsigned);
int recovery_exit_command_begin(struct recovery_exit_control *,bool,const struct recovery_exit_io *);
void recovery_exit_command_done(struct recovery_exit_control *);
void recovery_exit_transfer_started(struct recovery_exit_control *);
void recovery_exit_transfer_stopped(struct recovery_exit_control *);
int recovery_exit_transfer_complete(struct recovery_exit_control *,const struct recovery_exit_io *);
int recovery_exit_attempt(struct recovery_exit_control *,const struct recovery_exit_io *);
int recovery_exit_migration_request(struct recovery_exit_control *,const struct recovery_exit_io *);
void recovery_exit_migration_done(struct recovery_exit_control *,bool output_ok);
void recovery_exit_migration_cancel(struct recovery_exit_control *);
int recovery_exit_migration_attempt(struct recovery_exit_control *,const struct recovery_exit_io *);
int recovery_exit_sdk_reset_prepare(struct recovery_exit_control *,const struct recovery_exit_io *);
int recovery_exit_pairing_request(struct recovery_exit_control *,const struct recovery_exit_io *);
int recovery_exit_pairing_local_request(struct recovery_exit_control *,const struct recovery_exit_io *);
void recovery_exit_pairing_done(struct recovery_exit_control *,bool output_ok);
int recovery_exit_pairing_attempt(struct recovery_exit_control *,const struct recovery_exit_io *,int (*request)(void));
#endif
