/* SPDX-License-Identifier: Apache-2.0 */
#include "monitor.h"
#include <errno.h>
#include <string.h>
void common_restore_monitor_init(struct common_restore_monitor *m)
{memset(m,0,sizeof(*m));candidate_power_protection_init(&m->policy,NULL);}
COMMON_RESTORE_RAM void common_restore_monitor_sample(struct common_restore_monitor *m,uint64_t now,int raw)
{
 unsigned events=candidate_power_protection_sample(&m->policy,now,raw);
 if(events&(CANDIDATE_PROTECTION_TRIP|CANDIDATE_PROTECTION_INVALID|CANDIDATE_PROTECTION_GAP))m->cancelled=true;
}
int common_restore_monitor_arm(struct common_restore_monitor *m)
{
 if(candidate_power_protection_blocked(&m->policy)||!m->policy.stable_valid)return-EACCES;
 if(m->cancelled&&!m->policy.low_qualified)return-EACCES;
 m->cancelled=false;m->armed=true;return 0;
}
COMMON_RESTORE_RAM int common_restore_monitor_guard(const struct common_restore_monitor *m)
{return !m->armed||m->cancelled||candidate_power_protection_blocked(&m->policy)?-ECANCELED:0;}
