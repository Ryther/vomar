#ifndef VIMAR_RECOVERY_BOOT_HISTORY_H
#define VIMAR_RECOVERY_BOOT_HISTORY_H
#include <zcbor_encode.h>
#include "boot_trace.h"
#define VIMAR_BOOT_HISTORY_GROUP 0x8041u
bool recovery_boot_history_encode(zcbor_state_t *,const struct boot_trace_history *);
void recovery_boot_history_register(void);
#endif
