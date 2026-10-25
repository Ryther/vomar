/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_COMMON_RESTORE_BOOTSTRAP_H
#define VIMAR_COMMON_RESTORE_BOOTSTRAP_H
#include "common_restore.h"
/* Pinned-key ordinary RESTORE role4/profile2, linked at B0000 and ending below
 * EF000. Actual slot1 extends to F0000; RESTORE may not consume the original
 * EF000 page. This is separate from the role2 RECOVERY binary's34000 limit
 * and from the signed primary role3 containing this immutable blob. */
int common_restore_bootstrap_validate(const uint8_t *,size_t);
int common_restore_bootstrap_copy(struct common_restore *,uint64_t,uint32_t,uint32_t,const uint8_t *,size_t);
#endif
