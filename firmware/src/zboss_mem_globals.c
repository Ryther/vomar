/* SPDX-License-Identifier: LicenseRef-Nordic-5-Clause */
#include <zboss_api.h>
#include <zb_mem_config_med.h>

#if defined(CONFIG_VIMAR_FAULT_DIAGNOSTICS)
#include "fault_diag_sdk.h"
#include <stddef.h>

_Static_assert(sizeof(gc_sched_q_size) == 4, "scheduler capacity ABI");
_Static_assert(offsetof(zb_cb_q_buf_t, read_i) == 0 &&
               offsetof(zb_cb_q_buf_t, write_i) == 4 &&
               offsetof(zb_cb_q_buf_t, written) == 8 &&
               offsetof(zb_cb_q_buf_t, ring_buf) == 12, "scheduler header ABI");
_Static_assert(sizeof(gc_cb_q.ring_buf[0]) == 7 &&
               sizeof(gc_cb_q.ring_buf[0].u.func_ptr) == 4, "scheduler entry ABI");
_Static_assert(ZB_CONFIG_SCHEDULER_Q_SIZE == 32 && sizeof(gc_cb_q) == 236,
               "review changed native scheduler allocation");

uint32_t vimar_fault_diag_queue_snapshot(struct fault_diag_queue *out)
{
    const volatile zb_cb_q_buf_t *q = &gc_cb_q;
    *out = (struct fault_diag_queue){
        .capacity = *(const volatile zb_uint_t *)&gc_sched_q_size,
        .used = q->written, .read_index = q->read_i, .write_index = q->write_i,
    };
    uint32_t valid = FAULT_DIAG_VALID_QUEUE;
    /* Bound by the compiled allocation, never a possibly corrupt capacity. */
    if (out->capacity != 32 || out->used == 0 || out->used > 32 ||
        out->read_index >= 32 || out->write_index >= 32 ||
        (out->read_index + out->used) % 32 != out->write_index) return valid;
    out->head_callback = (uint32_t)(uintptr_t)q->ring_buf[out->read_index].u.func_ptr;
    out->tail_callback = (uint32_t)(uintptr_t)q->ring_buf[(out->write_index + 31) % 32].u.func_ptr;
    if (out->head_callback != 0) valid |= FAULT_DIAG_VALID_QUEUE_HEAD;
    if (out->tail_callback != 0) valid |= FAULT_DIAG_VALID_QUEUE_TAIL;
    return valid;
}
#endif
