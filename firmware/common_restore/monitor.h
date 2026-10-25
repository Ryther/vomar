/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_COMMON_RESTORE_MONITOR_H
#define VIMAR_COMMON_RESTORE_MONITOR_H
#include "candidate_power_protection.h"
#include "ram.h"
/* Volatile maintenance policy only: no NVS, retained trip claim, or ON action.
 * Init after reset loses prior volatile evidence. A fresh table and explicit
 * Begin are required; this is not the normal recovery persistence adapter. */
struct common_restore_monitor {struct candidate_power_protection policy;bool armed,cancelled;};
void common_restore_monitor_init(struct common_restore_monitor *);
COMMON_RESTORE_RAM void common_restore_monitor_sample(struct common_restore_monitor *,uint64_t,int);
int common_restore_monitor_arm(struct common_restore_monitor *);
COMMON_RESTORE_RAM int common_restore_monitor_guard(const struct common_restore_monitor *);
#endif
