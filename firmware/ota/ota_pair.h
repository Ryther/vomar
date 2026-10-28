/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_OTA_PAIR_H
#define VIMAR_OTA_PAIR_H
#include "ota_image.h"
/* Caller provides release-authorized loader hashes, never hashes learned from
 * the journal. Operation identity is pinned by the authenticated handoff.
 * mapped may be zero on MCU; mapped_size still bounds every physical access. */
int ota_pair_verify(const uint8_t *mapped,size_t mapped_size,const uint8_t (*loaders)[32],size_t count,
 const uint8_t expected_recovery[32],uint8_t actual_loader[32],struct ota_image_info *recovery);
/* MAIN admission requires the stable signed RECOVERY2/profile2 ABI, not an
 * exact release hash. Captured actual digests still bind each transaction. */
int ota_pair_authenticate(const uint8_t *mapped,size_t mapped_size,const uint8_t (*loaders)[32],size_t count,
 uint8_t actual_loader[32],struct ota_image_info *recovery);
#endif
