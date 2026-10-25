/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_COMMON_RESTORE_PLATFORM_H
#define VIMAR_COMMON_RESTORE_PLATFORM_H
#include "common_restore.h"
extern struct common_restore common_restore_state;
int common_restore_platform_init(void);
const struct common_restore_io *common_restore_platform_io(void);
void common_restore_platform_peer(uint32_t,bool);
void common_restore_platform_operation(uint32_t);
bool common_restore_platform_quiescing(void);
unsigned common_restore_platform_flags(void);
const struct loader_contract_record *common_restore_platform_records(size_t *);
unsigned common_restore_platform_role(void);
void common_restore_platform_blob(const uint8_t **,size_t *);
#endif
