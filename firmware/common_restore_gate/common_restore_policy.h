/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_COMMON_RESTORE_POLICY_H
#define VIMAR_COMMON_RESTORE_POLICY_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "loader_contract.h"
#define COMMON_RESTORE_SLOT 0xb0000u
#define COMMON_RESTORE_LIMIT 0x3f000u
struct common_restore_image {
 uint32_t size, payload_size;
 uint8_t role, profile;
};
/* Pure bounded parsing: success is NOT signature verification. It must be
 * combined with the actual selected image's fresh real MCUboot result below.
 * Output publication/zeroing follows all input reads, including for aliases. */
int common_restore_parse(const uint8_t *, size_t, struct common_restore_image *);
/* Adapter alone owns real_boot_validated, derived from FIH __real_boot_go.
 * No retained request, request parameter or header can supply this authority.
 * A failed admission changes no boot result and grants no flash/ACL operation. */
int common_restore_admit(bool real_boot_validated, unsigned device, uint32_t selected_offset,
 const uint8_t *image, size_t capacity, const uint8_t *anchor, size_t anchor_size,
 const struct loader_contract_live *live);
#endif
