/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_OTA_SPLIT_STAGE_H
#define VIMAR_OTA_SPLIT_STAGE_H
#include <stdint.h>
#include <stddef.h>
#define OTA_SPLIT_SECOND_START UINT32_C(0xe4000)
#define OTA_SPLIT_SECOND_END UINT32_C(0xef000)
struct ota_split_bounds {uint32_t start,end,second_start,second_end,payload_size;};
int ota_split_validate(const struct ota_split_bounds *);
int ota_split_plan(uint32_t current_end,uint32_t payload_size,uint32_t destination_end,uint32_t recovery_end,struct ota_split_bounds *);
/* Available is limited to the current extent and logical payload remainder. */
int ota_split_map(const struct ota_split_bounds *,uint32_t logical,uint32_t *physical,uint32_t *available);
struct ota_split_transfer {
 struct ota_split_bounds bounds;uint32_t next_offset;void *context;
 int (*read)(void*,uint32_t,uint8_t*,size_t);
 int (*write)(void*,uint32_t,const uint8_t*,size_t);
};
int ota_split_accept(struct ota_split_transfer*,uint32_t,const uint8_t*,size_t);
#endif
