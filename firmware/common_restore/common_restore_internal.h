/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_COMMON_RESTORE_INTERNAL_H
#define VIMAR_COMMON_RESTORE_INTERNAL_H
#include "common_restore.h"
int common_restore_sequence(struct common_restore *,uint64_t,uint32_t,uint32_t);
int common_restore_revalidate(struct common_restore *);
int common_restore_guard(struct common_restore *);
int common_restore_fail(struct common_restore *,int);
#endif
