/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_OTA_PAIR_H
#define VIMAR_OTA_PAIR_H
#include "ota_image.h"
/* Caller provides release-authorized loader hashes, never hashes learned from
 * the journal. Recovery identity is pinned by main or its authenticated handoff.
 * mapped may be zero on MCU; mapped_size still bounds every physical access. */
int ota_pair_verify(const uint8_t *mapped,size_t mapped_size,const uint8_t (*loaders)[32],size_t count,
 const uint8_t expected_recovery[32],uint8_t actual_loader[32],struct ota_image_info *recovery);
#endif
