/* SPDX-License-Identifier: LicenseRef-Nordic-5-Clause */
#include <zboss_api.h>
#include <zb_mem_config_med.h>
#include <string.h>

#if defined(CONFIG_VIMAR_ZIGBEE_DIAGNOSTIC_BATCH)
#include <zb_common.h>
#include "zigbee_alloc_trace.h"
#include "fault_diag_sdk.h"
#include <stddef.h>
_Static_assert(offsetof(__typeof__(*ZG), bpool.bufs_allocated) == 0x10c,
               "Review native pool counter ABI");
_Static_assert(sizeof(gc_bufs_busy_bitmap) <= 5, "Review larger native pool bitmap");
_Static_assert(offsetof(__typeof__(*ZG), sched.delayed_queue) == 0x74 &&
               sizeof(zb_delayed_buf_q_ent_t) == 7 && sizeof(zb_delayed_cb_q_t) == 68 &&
               offsetof(zb_delayed_cb_q_t, ring_buf) == 12 && ZB_BUF_Q_SIZE == 8,
               "Review native delayed-buffer ring ABI");

bool vimar_alloc_trace_delayed_snapshot(uint8_t direction, struct vimar_alloc_delayed_queue *out)
{
    *out = (struct vimar_alloc_delayed_queue){0};
    if (direction > 1) return false;
    const zb_delayed_cb_q_t *queue = &ZG->sched.delayed_queue[direction];
    *out = (struct vimar_alloc_delayed_queue) {
        .entries = (const uint8_t *)queue->ring_buf,
        .read = queue->read_i, .write = queue->write_i, .count = queue->written,
    };
    return queue->read_i < 8 && queue->write_i < 8 && queue->written <= 8 &&
           (queue->read_i + queue->written) % 8 == queue->write_i;
}

void vimar_alloc_trace_pool_snapshot(struct vimar_alloc_pool_state *out)
{
    struct fault_diag_queue queue = {0};
    (void)vimar_fault_diag_queue_snapshot(&queue);
    *out = (struct vimar_alloc_pool_state){
        .out = ZG->bpool.bufs_allocated[0], .in = ZG->bpool.bufs_allocated[1],
        .pool_size = gc_pool_size <= VIMAR_ALLOC_TRACE_POOL ? gc_pool_size : 0,
        .queue_used = queue.used <= 255u ? queue.used : 255u,
        .head = queue.head_callback, .tail = queue.tail_callback,
    };
    if (queue.capacity == 32 && queue.used <= 32 && queue.read_index < 32 &&
            queue.write_index < 32 && (queue.read_index + queue.used) % 32 == queue.write_index)
        out->valid |= 1u;
    if (gc_pool_size > 0 && gc_pool_size <= VIMAR_ALLOC_TRACE_POOL &&
            gc_buf_pool_bitmap_size == (gc_pool_size + 7u) / 8u) {
        memcpy(out->bitmap, gc_bufs_busy_bitmap, gc_buf_pool_bitmap_size);
        out->valid |= 2u;
    }
}
#endif

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
