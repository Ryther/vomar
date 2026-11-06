/* Experimental counted batch for the pinned precompiled SDK. */
#include "zigbee_diag_batch.h"
#include <stdbool.h>
#include <stdint.h>
#include <zephyr/irq.h>
#include <zb_common.h>
#include <zb_scheduler.h>

_Static_assert(sizeof(ZDO_DIAGNOSTICS_CTX().diagnostics_info.packet_buffer_allocate_failures) == 2,
               "Review changed native diagnostic counter ABI");

extern zb_ret_t __real_zb_schedule_callback(zb_callback_t, zb_uint8_t);
static uint16_t vimar_diag_batch_pending;
static bool vimar_diag_batch_scheduled;
static uint32_t allocation_arrivals, checkpoints;
/* Only the serialized diagnostic consumer reads or updates this clock state. */
static zb_time_t last_delivery;
static bool have_delivery;

zb_ret_t vimar_diag_statistics_checkpoint(zb_nvram_dataset_types_t dataset)
{
    if (dataset != ZB_NVRAM_ZDO_DIAGNOSTICS_DATA) zb_osif_abort();
    unsigned key = irq_lock();
    ++checkpoints;
    irq_unlock(key);
    return RET_OK;
}

void vimar_diag_statistics_snapshot(struct vimar_diag_statistics *snapshot)
{
    unsigned key = irq_lock();
    *snapshot = (struct vimar_diag_statistics) {
        .status = 1u | (vimar_diag_batch_scheduled ? 2u : 0u),
        .allocation_arrivals = allocation_arrivals,
        .checkpoints = checkpoints,
        .sdk_allocation_failures = ZDO_DIAGNOSTICS_CTX().diagnostics_info.packet_buffer_allocate_failures,
        .pending = vimar_diag_batch_pending,
    };
    irq_unlock(key);
}

static void vimar_diag_batch_deliver(zb_uint8_t parameter)
{
    /* App translation units do not enable the SDK's optional ZB_ASSERT. */
    if (parameter != 0) zb_osif_abort();
    zb_time_t now = ZB_TIMER_GET();
    unsigned key = irq_lock();
    if (!vimar_diag_batch_scheduled) zb_osif_abort();
    zb_time_t elapsed = (zb_time_t)(now - last_delivery);
    if (have_delivery && elapsed < ZB_TIME_ONE_SECOND) {
        irq_unlock(key);
        /* Keep the admitted batch pending while ordinary scheduler work runs. */
        zb_ret_t result = zb_schedule_alarm(vimar_diag_batch_deliver, 0,
                                            ZB_TIME_ONE_SECOND - elapsed);
        if (result != RET_OK) zb_osif_abort();
        return;
    }
    uint16_t batch = vimar_diag_batch_pending;
    vimar_diag_batch_pending = 0;
    vimar_diag_batch_scheduled = false;
    /* A zero batch represents a multiple of65536 failures, not an empty queue. */
    ZDO_DIAGNOSTICS_CTX().diagnostics_info.packet_buffer_allocate_failures =
        (uint16_t)(ZDO_DIAGNOSTICS_CTX().diagnostics_info.packet_buffer_allocate_failures
                   + (uint32_t)batch - 1u);
    irq_unlock(key);
    vimar_sdk_buf_diag_handle_alloc_failure(0);
    last_delivery = ZB_TIMER_GET();
    have_delivery = true;
}

zb_ret_t vimar_diag_batch_schedule(zb_uint8_t parameter)
{
    if (parameter != 0) zb_osif_abort();
    unsigned key = irq_lock();
    ++allocation_arrivals;
    vimar_diag_batch_pending = (uint16_t)(vimar_diag_batch_pending + 1u);
    if (vimar_diag_batch_scheduled) {
        irq_unlock(key);
        return RET_OK;
    }
    vimar_diag_batch_scheduled = true;
    irq_unlock(key);
    zb_ret_t result = __real_zb_schedule_callback(vimar_diag_batch_deliver, 0);
    if (result != RET_OK) {
        key = irq_lock();
        vimar_diag_batch_scheduled = false;
        irq_unlock(key);
    }
    return result;
}
