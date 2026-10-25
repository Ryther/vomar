#ifndef VIMAR_MIGRATION_POLICY_H
#define VIMAR_MIGRATION_POLICY_H
#include "research_handoff.h"
/* A missing transaction is0/-ENOENT. Any retained bytes must be resolved before
 * replacing recovery. Legacy ON lacks protection authorization: reject without
 * consuming it; legacy OFF can be cleared. Protected handoff is only peeked. */
int migration_protection_preflight(int,const struct research_handoff_io*);
#endif
