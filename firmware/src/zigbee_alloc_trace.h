/* Bounded volatile refusal evidence for the reviewed SDK ABI. */
#ifndef VIMAR_ZIGBEE_ALLOC_TRACE_H
#define VIMAR_ZIGBEE_ALLOC_TRACE_H
#include <stdint.h>
#include <stdbool.h>

#define VIMAR_ALLOC_TRACE_CAPACITY 32u
#define VIMAR_ALLOC_TRACE_POOL 40u
#define VIMAR_ALLOC_TRACE_HOLDER_CHUNKS 14u
#define VIMAR_ALLOC_DELAYED_CAPACITY 8u
struct vimar_alloc_delayed_queue {
    const uint8_t *entries;
    uint8_t read, write, count;
};
bool vimar_alloc_trace_delayed_snapshot(uint8_t direction, struct vimar_alloc_delayed_queue *out);
struct vimar_alloc_pool_state {
    uint8_t out, in, pool_size, queue_used;
    uint32_t head, tail;
    uint8_t bitmap[5], valid;
};
struct vimar_alloc_failure {
    uint32_t sequence, time_ms, caller, requested_bytes;
    uint8_t bitmap[5], flags, units, out;
    uint8_t in, queue_used, pool_size, valid;
    uint32_t head, tail, oldest_caller, oldest_age_ms;
    uint8_t oldest_id, oldest_units, reserved[2];
};
_Static_assert(sizeof(struct vimar_alloc_failure) == 48, "Allocation record ABI");
extern uint8_t vimar_alloc_trace_metadata[21];
extern uint8_t vimar_alloc_trace_first[49], vimar_alloc_trace_latest[49];
extern uint8_t vimar_alloc_trace_history[VIMAR_ALLOC_TRACE_CAPACITY][49];
extern uint8_t vimar_alloc_trace_holders[VIMAR_ALLOC_TRACE_HOLDER_CHUNKS][41];
extern uint8_t vimar_alloc_trace_previous[3][33];
extern uint32_t vimar_alloc_trace_retained_status;
extern uint32_t vimar_alloc_trace_dropped, vimar_alloc_trace_lifetime_gaps;
void vimar_alloc_trace_boot(uint32_t boot_sequence);
void vimar_alloc_trace_flush(void);
void vimar_alloc_trace_pool_snapshot(struct vimar_alloc_pool_state *state);
void vimar_alloc_trace_storage_result(uint8_t units, uint8_t first_buffer);
void vimar_alloc_trace_release(uint8_t first_buffer);
void vimar_alloc_trace_pool_reset(void);
void vimar_alloc_trace_failure(void);
void vimar_alloc_trace_refresh(void);
#endif
