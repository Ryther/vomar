#ifndef VIMAR_ZIGBEE_DIAG_BATCH_H
#define VIMAR_ZIGBEE_DIAG_BATCH_H
#include <zboss_api.h>
#include <stdint.h>
struct vimar_diag_statistics {
    uint32_t status, allocation_arrivals, checkpoints;
    uint16_t sdk_allocation_failures, pending;
};
extern void vimar_sdk_buf_diag_handle_alloc_failure(zb_uint8_t parameter);
zb_ret_t vimar_diag_batch_schedule(zb_uint8_t parameter);
zb_ret_t vimar_diag_statistics_checkpoint(zb_nvram_dataset_types_t dataset);
void vimar_diag_statistics_snapshot(struct vimar_diag_statistics *snapshot);
#endif
