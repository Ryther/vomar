const unsigned int vimar_alloc_trace_enabled = 1;
/* Failure-time RAM acquisition; no allocation, flash, or radio calls. */
#include "zigbee_alloc_trace.h"
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <zboss_api.h>
#include <zephyr/irq.h>
#include <zephyr/kernel.h>
#include VIMAR_FAULT_BUILD_ID_HEADER
#ifndef ALLOC_RETAINED
#include <zephyr/devicetree.h>
_Static_assert(DT_REG_ADDR(DT_NODELABEL(sram0)) == UINT32_C(0x20000000) &&
               DT_REG_SIZE(DT_NODELABEL(sram0)) <= UINT32_C(0x3fc00),
               "Allocation trace requires its reserved SRAM overlay");
/* shortcut: loader/REC free heaps may overwrite retained RAM; qualify each
 * transition before relying on it. CRC rejects incomplete or damaged commits. */
#define ALLOC_RETAINED ((volatile uint32_t *)UINT32_C(0x2003fc00))
#endif

_Static_assert(__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__, "Reviewed trace byte order");
struct allocation_context {
    struct allocation_context *previous;
    uint32_t caller, requested_bytes;
    uint8_t direction, units, storage_flags;
    uint8_t delayed_entry[7];
    uint32_t epoch, integrity;
    bool delayed_request, entry_seen, assigned, queue_valid, queued;
};
struct context_slot {
    struct allocation_context *active;
    void *thread;
    bool isr;
};
struct holder {
    uint32_t caller, time_ms;
    uint8_t units, direction, flags;
};
struct holder_view {
    uint32_t caller, age_ms;
    uint8_t id, units, direction, flags;
};
_Static_assert(sizeof(struct holder_view) == 12, "Holder view ABI");
static struct context_slot contexts[4];
static struct {
    uint32_t caller, requested_bytes, integrity;
    uint8_t entry[7];
    bool valid;
} delayed_origins[2][VIMAR_ALLOC_DELAYED_CAPACITY];
static uint32_t delayed_epoch, delayed_integrity;
static struct holder holders[VIMAR_ALLOC_TRACE_POOL];
static struct holder_view failure_holders[VIMAR_ALLOC_TRACE_POOL];
static struct vimar_alloc_failure history[VIMAR_ALLOC_TRACE_CAPACITY], first_record;
static uint32_t total, overwritten, missing_context, published;
static uint8_t retained;
static bool initialized;
static bool counter_wrapped, history_overwritten;
static volatile bool capture_busy, holders_uncertain;
static volatile uint32_t sampled_time;
uint8_t vimar_alloc_trace_metadata[21];
uint8_t vimar_alloc_trace_first[49], vimar_alloc_trace_latest[49];
uint8_t vimar_alloc_trace_history[VIMAR_ALLOC_TRACE_CAPACITY][49];
uint8_t vimar_alloc_trace_holders[VIMAR_ALLOC_TRACE_HOLDER_CHUNKS][41];
uint8_t vimar_alloc_trace_previous[3][33];
uint32_t vimar_alloc_trace_retained_status;
uint32_t vimar_alloc_trace_dropped, vimar_alloc_trace_lifetime_gaps;
struct retained_failure {
    uint32_t magic, version, generation, boot;
    uint8_t build_id[16];
    struct vimar_alloc_failure record;
    uint32_t crc, commit;
};
_Static_assert(sizeof(struct retained_failure) == 88 &&
               offsetof(struct retained_failure, crc) == 80, "Retained allocation ABI");
static uint32_t retained_generation, retained_boot, retained_at, retained_sequence;
static unsigned retained_slot;
static bool retained_written;
static volatile bool retained_ready;
static volatile bool retained_busy;
static void retain_failure(const struct vimar_alloc_failure *record, uint32_t now, bool force);
extern zb_bufid_t vimar_sdk_buf_get_func(zb_bool_t, zb_uint_t);
extern zb_bufid_t vimar_sdk_zb_buf_get_hipri_func(zb_bool_t);
extern zb_ret_t vimar_sdk_zb_buf_get_out_delayed_func(zb_callback_t);
extern zb_ret_t vimar_sdk_zb_buf_get_in_delayed_func(zb_callback_t);
extern zb_ret_t vimar_sdk_zb_buf_get_out_delayed_ext_func(zb_callback2_t, zb_uint16_t, zb_uint_t);
extern zb_ret_t vimar_sdk_zb_buf_get_in_delayed_ext_func(zb_callback2_t, zb_uint16_t, zb_uint_t);
extern zb_bool_t vimar_sdk_process_delayed_buf_entry_unsafe(void *, zb_bool_t);

static uint32_t trace_now(bool *cached)
{
    *cached = k_is_in_isr();
    if (*cached) return sampled_time;
    unsigned key = irq_lock();
    uint32_t now = k_uptime_get_32();
    sampled_time = now;
    irq_unlock(key);
    return now;
}

static void lifetime_gap(void)
{
    (void)__atomic_fetch_add(&vimar_alloc_trace_lifetime_gaps, 1u, __ATOMIC_RELAXED);
    holders_uncertain = true;
}

static void delayed_gap(void)
{
    (void)__atomic_fetch_add(&delayed_integrity, 1u, __ATOMIC_RELAXED);
    lifetime_gap();
}

static struct context_slot *context_slot(bool reserve)
{
    void *thread = k_current_get();
    bool isr = k_is_in_isr();
    struct context_slot *available = NULL;
    for (unsigned i = 0; i < 4; ++i) {
        struct context_slot *slot = &contexts[i];
        if (slot->active && slot->thread == thread && slot->isr == isr) return slot;
        if (!slot->active && available == NULL) available = slot;
    }
    if (reserve && available != NULL) {
        available->thread = thread;
        available->isr = isr;
        return available;
    }
    return NULL;
}

static struct allocation_context *current_context(void)
{
    struct context_slot *slot = context_slot(false);
    struct allocation_context *context = slot ? slot->active : NULL;
    return context && context->caller && context->epoch == delayed_epoch &&
        (!context->queued || context->integrity == delayed_integrity) ? context : NULL;
}

static struct context_slot *context_enter(struct allocation_context *context)
{
    unsigned key = irq_lock();
    struct context_slot *slot = NULL;
    bool busy = capture_busy;
    capture_busy = true;
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    if (!busy) slot = context_slot(true);
    if (slot != NULL) {
        context->previous = slot->active;
        context->epoch = delayed_epoch;
        slot->active = context;
    }
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    capture_busy = busy;
    irq_unlock(key);
    return slot;
}

static void context_leave(struct context_slot *slot, struct allocation_context *context)
{
    unsigned key = irq_lock();
    bool busy = capture_busy;
    capture_busy = true;
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    if (slot != NULL) slot->active = context->previous;
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    capture_busy = busy;
    irq_unlock(key);
}

zb_bufid_t zb_buf_get_func(zb_bool_t is_in, zb_uint_t size)
{
    struct allocation_context context = {
        .caller = (uint32_t)(uintptr_t)__builtin_return_address(0),
        .requested_bytes = size, .direction = is_in != 0,
    };
    struct context_slot *slot = context_enter(&context);
    zb_bufid_t buffer = vimar_sdk_buf_get_func(is_in, size);
    context_leave(slot, &context);
    return buffer;
}

zb_bufid_t zb_buf_get_hipri_func(zb_bool_t is_in)
{
    struct allocation_context context = {
        .caller = (uint32_t)(uintptr_t)__builtin_return_address(0), .direction = is_in != 0,
    };
    struct context_slot *slot = context_enter(&context);
    zb_bufid_t buffer = vimar_sdk_zb_buf_get_hipri_func(is_in);
    context_leave(slot, &context);
    return buffer;
}

static struct context_slot *delayed_enter(struct allocation_context *context,
                                        struct vimar_alloc_delayed_queue *before)
{
    context->delayed_request = true;
    struct context_slot *slot = context_enter(context);
    unsigned key = irq_lock();
    context->integrity = delayed_integrity;
    context->queue_valid = vimar_alloc_trace_delayed_snapshot(context->direction, before);
    irq_unlock(key);
    return slot;
}

static void delayed_leave(struct allocation_context *context, struct context_slot *slot,
                          const struct vimar_alloc_delayed_queue *before, zb_ret_t result)
{
    unsigned key = irq_lock();
    bool busy = capture_busy;
    capture_busy = true;
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    if (result == RET_OK && !context->assigned) {
        struct vimar_alloc_delayed_queue after = {0};
        bool valid = !busy && slot != NULL && context->epoch == delayed_epoch &&
            context->integrity == delayed_integrity &&
            context->queue_valid && context->entry_seen &&
            vimar_alloc_trace_delayed_snapshot(context->direction, &after) &&
            before->count < VIMAR_ALLOC_DELAYED_CAPACITY && after.read == before->read &&
            after.count == before->count + 1u &&
            after.write == (before->write + 1u) % VIMAR_ALLOC_DELAYED_CAPACITY &&
            before->entries == after.entries &&
            memcmp(after.entries + 7u * before->write, context->delayed_entry, 7) == 0;
        if (valid) {
            unsigned index = before->write;
            delayed_origins[context->direction][index].caller = context->caller;
            delayed_origins[context->direction][index].requested_bytes = context->requested_bytes;
            delayed_origins[context->direction][index].integrity = context->integrity;
            memcpy(delayed_origins[context->direction][index].entry, context->delayed_entry, 7);
            delayed_origins[context->direction][index].valid = true;
        } else delayed_gap();
    }
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    capture_busy = busy;
    irq_unlock(key);
    context_leave(slot, context);
}

zb_ret_t zb_buf_get_out_delayed_func(zb_callback_t callback)
{
    struct allocation_context context = {.caller = (uint32_t)(uintptr_t)__builtin_return_address(0)};
    struct vimar_alloc_delayed_queue before = {0};
    struct context_slot *slot = delayed_enter(&context, &before);
    zb_ret_t result = vimar_sdk_zb_buf_get_out_delayed_func(callback);
    delayed_leave(&context, slot, &before, result);
    return result;
}

zb_ret_t zb_buf_get_in_delayed_func(zb_callback_t callback)
{
    struct allocation_context context = {
        .caller = (uint32_t)(uintptr_t)__builtin_return_address(0), .direction = 1,
    };
    struct vimar_alloc_delayed_queue before = {0};
    struct context_slot *slot = delayed_enter(&context, &before);
    zb_ret_t result = vimar_sdk_zb_buf_get_in_delayed_func(callback);
    delayed_leave(&context, slot, &before, result);
    return result;
}

zb_ret_t zb_buf_get_out_delayed_ext_func(zb_callback2_t callback, zb_uint16_t arg, zb_uint_t size)
{
    struct allocation_context context = {
        .caller = (uint32_t)(uintptr_t)__builtin_return_address(0), .requested_bytes = size,
    };
    struct vimar_alloc_delayed_queue before = {0};
    struct context_slot *slot = delayed_enter(&context, &before);
    zb_ret_t result = vimar_sdk_zb_buf_get_out_delayed_ext_func(callback, arg, size);
    delayed_leave(&context, slot, &before, result);
    return result;
}

zb_ret_t zb_buf_get_in_delayed_ext_func(zb_callback2_t callback, zb_uint16_t arg, zb_uint_t size)
{
    struct allocation_context context = {
        .caller = (uint32_t)(uintptr_t)__builtin_return_address(0),
        .requested_bytes = size, .direction = 1,
    };
    struct vimar_alloc_delayed_queue before = {0};
    struct context_slot *slot = delayed_enter(&context, &before);
    zb_ret_t result = vimar_sdk_zb_buf_get_in_delayed_ext_func(callback, arg, size);
    delayed_leave(&context, slot, &before, result);
    return result;
}

zb_bool_t process_delayed_buf_entry_unsafe(void *entry, zb_bool_t is_in)
{
    struct vimar_alloc_delayed_queue queue = {0};
    struct allocation_context restored = {.direction = is_in != 0};
    unsigned key = irq_lock();
    bool busy = capture_busy;
    capture_busy = true;
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    uint32_t epoch = delayed_epoch;
    uint32_t integrity = delayed_integrity;
    bool valid = vimar_alloc_trace_delayed_snapshot(restored.direction, &queue);
    uintptr_t base = (uintptr_t)queue.entries, address = (uintptr_t)entry;
    bool ring = base && address >= base && address < base + 7u * VIMAR_ALLOC_DELAYED_CAPACITY;
    unsigned index = ring ? (unsigned)((address - base) / 7u) : 0;
    bool inherit_request = false;
    if (ring) {
        restored.queued = true;
        restored.integrity = integrity;
        if (!busy && valid && queue.count && address == base + 7u * queue.read &&
                delayed_origins[restored.direction][index].valid &&
                delayed_origins[restored.direction][index].integrity == integrity &&
                memcmp(entry, delayed_origins[restored.direction][index].entry, 7) == 0) {
            restored.caller = delayed_origins[restored.direction][index].caller;
            restored.requested_bytes = delayed_origins[restored.direction][index].requested_bytes;
        } else delayed_gap();
    } else {
        struct allocation_context *context = current_context();
        if (!busy && context && context->delayed_request && context->direction == restored.direction) {
            memcpy(context->delayed_entry, entry, 7);
            context->entry_seen = true;
            inherit_request = true;
        } else delayed_gap();
    }
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    capture_busy = busy;
    irq_unlock(key);
    /* A queued request must never inherit the caller of the free that serves it. */
    bool scoped = !inherit_request;
    struct context_slot *slot = scoped ? context_enter(&restored) : NULL;
    if (scoped && (epoch != restored.epoch || integrity != delayed_integrity)) restored.caller = 0;
    zb_bool_t result = vimar_sdk_process_delayed_buf_entry_unsafe(entry, is_in);
    if (ring) {
        key = irq_lock();
        busy = capture_busy;
        capture_busy = true;
        __atomic_thread_fence(__ATOMIC_SEQ_CST);
        if (result) {
            if (!busy && epoch == delayed_epoch && integrity == delayed_integrity)
                delayed_origins[restored.direction][index].valid = false;
            else delayed_gap();
        }
        __atomic_thread_fence(__ATOMIC_SEQ_CST);
        capture_busy = busy;
        irq_unlock(key);
    }
    if (scoped) context_leave(slot, &restored);
    return result;
}

void vimar_alloc_trace_pool_reset(void)
{
    unsigned key = irq_lock();
    if (capture_busy) { delayed_gap(); irq_unlock(key); return; }
    capture_busy = true;
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    memset(holders, 0, sizeof(holders));
    memset(delayed_origins, 0, sizeof(delayed_origins));
    ++delayed_epoch;
    ++delayed_integrity;
    holders_uncertain = false;
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    capture_busy = false;
    irq_unlock(key);
}

void vimar_alloc_trace_storage_result(uint8_t units, uint8_t first_buffer)
{
    unsigned key = irq_lock();
    bool cached;
    uint32_t now = trace_now(&cached);
    if (capture_busy) { lifetime_gap(); irq_unlock(key); return; }
    capture_busy = true;
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    struct allocation_context *context = current_context();
    if (context != NULL) {
        context->units = units;
        context->storage_flags = 4u | (first_buffer == 0 ? 8u : 0u);
        context->assigned |= first_buffer != 0;
    }
    if (first_buffer != 0 && first_buffer <= VIMAR_ALLOC_TRACE_POOL &&
            units != 0 && units <= VIMAR_ALLOC_TRACE_POOL + 1u - first_buffer) {
        holders[first_buffer - 1] = (struct holder) {
            .caller = context ? context->caller : 0, .time_ms = now,
            .units = units, .direction = context ? context->direction : 0xff,
            .flags = 1u | (context ? 2u : 0u) | (cached ? 4u : 0u),
        };
    }
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    capture_busy = false;
    irq_unlock(key);
}

void vimar_alloc_trace_release(uint8_t first_buffer)
{
    unsigned key = irq_lock();
    if (capture_busy) { lifetime_gap(); irq_unlock(key); return; }
    capture_busy = true;
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    if (first_buffer != 0 && first_buffer <= VIMAR_ALLOC_TRACE_POOL)
        memset(&holders[first_buffer - 1], 0, sizeof(holders[0]));
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    capture_busy = false;
    irq_unlock(key);
}

void vimar_alloc_trace_failure(void)
{
    unsigned key = irq_lock();
    bool cached;
    uint32_t now = trace_now(&cached);
    if (capture_busy) {
        (void)__atomic_fetch_add(&vimar_alloc_trace_dropped, 1u, __ATOMIC_RELAXED);
        irq_unlock(key);
        return;
    }
    capture_busy = true;
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    uint32_t gaps_before = __atomic_load_n(&vimar_alloc_trace_lifetime_gaps, __ATOMIC_RELAXED);
    struct allocation_context *context = current_context();
    struct vimar_alloc_pool_state pool;
    vimar_alloc_trace_pool_snapshot(&pool);
    struct vimar_alloc_failure record = {
        .sequence = ++total, .time_ms = now,
        .caller = context ? context->caller : 0,
        .requested_bytes = context ? context->requested_bytes : 0,
        .flags = (context ? (uint8_t)(2u | context->direction | context->storage_flags) : 0) | (cached ? 16u : 0u),
        .units = context ? context->units : 0, .out = pool.out, .in = pool.in,
        .queue_used = pool.queue_used, .pool_size = pool.pool_size,
        .head = pool.head, .tail = pool.tail, .valid = pool.valid,
    };
    memcpy(record.bitmap, pool.bitmap, sizeof(record.bitmap));
    if (total == 0) counter_wrapped = true;
    if (context == NULL) ++missing_context;
    uint8_t covered[5] = {0};
    bool coverage_valid = true;
    for (unsigned i = 0; i < VIMAR_ALLOC_TRACE_POOL; ++i) {
        struct holder *holder = &holders[i];
        failure_holders[i] = (struct holder_view){0};
        if (!(holder->flags & 1u)) continue;
        if (holder->units == 0 || holder->units > VIMAR_ALLOC_TRACE_POOL - i) {
            coverage_valid = false;
            continue;
        }
        for (unsigned j = 0; j < holder->units; ++j)
            covered[(i + j) / 8] |= 1u << ((i + j) % 8);
        uint32_t age = now - holder->time_ms;
        failure_holders[i] = (struct holder_view) {
            .caller = holder->caller, .age_ms = age, .id = i + 1,
            .units = holder->units, .direction = holder->direction,
            .flags = holder->flags | (cached ? 4u : 0u),
        };
        if (record.oldest_id == 0 || age > record.oldest_age_ms) {
            record.oldest_id = i + 1;
            record.oldest_units = holder->units;
            record.oldest_age_ms = age;
            record.oldest_caller = holder->caller;
            record.valid = (record.valid & 3u) | 4u | ((holder->flags & 2u) ? 8u : 0u)
                           | ((holder->flags & 4u) ? 16u : 0u);
        }
    }
    if (gaps_before != __atomic_load_n(&vimar_alloc_trace_lifetime_gaps, __ATOMIC_RELAXED))
        record.valid &= ~2u;
    if (holders_uncertain || !coverage_valid ||
            ((pool.valid & 2u) && memcmp(covered, pool.bitmap, sizeof(covered)) != 0)) {
        record.valid = (record.valid & ~12u) | 32u;
        for (unsigned i = 0; i < VIMAR_ALLOC_TRACE_POOL; ++i)
            if (failure_holders[i].flags & 1u) failure_holders[i].flags |= 8u;
    }
    if (retained == 0) first_record = record;
    if (retained < VIMAR_ALLOC_TRACE_CAPACITY) ++retained;
    else { ++overwritten; history_overwritten = true; }
    history[(total - 1u) % VIMAR_ALLOC_TRACE_CAPACITY] = record;
    retain_failure(&record, now, false);
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    capture_busy = false;
    irq_unlock(key);
}

static uint32_t retained_crc(const uint8_t *bytes)
{
    uint32_t crc = UINT32_MAX;
    for (unsigned i = 0; i < 80; ++i) {
        crc ^= bytes[i];
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ ((crc & 1u) ? UINT32_C(0xedb88320) : 0u);
    }
    return ~crc;
}

static bool read_retained(unsigned slot, struct retained_failure *record)
{
    uint32_t words[22];
    for (unsigned i = 0; i < 22; ++i) words[i] = ALLOC_RETAINED[slot * 32 + i];
    memcpy(record, words, sizeof(*record));
    return record->magic == UINT32_C(0x414c4c43) && record->version == 1 &&
        record->commit == UINT32_C(0x41545243) &&
        record->crc == retained_crc((const uint8_t *)record);
}

void vimar_alloc_trace_boot(uint32_t boot_sequence)
{
    unsigned key = irq_lock();
    struct retained_failure a, b;
    bool va = read_retained(0, &a), vb = read_retained(1, &b);
    const struct retained_failure *previous = va ? &a : NULL;
    unsigned latest_slot = 0;
    if (vb && (!va || (b.generation != a.generation &&
            (uint32_t)(b.generation - a.generation) < UINT32_C(0x80000000)))) {
        previous = &b;
        latest_slot = 1;
    }
    uint8_t raw[96] = {0};
    vimar_alloc_trace_retained_status = 1u;
    if (previous != NULL) {
        memcpy(raw, previous, sizeof(*previous));
        retained_generation = previous->generation;
        vimar_alloc_trace_retained_status |= 2u;
        if (memcmp(previous->build_id, vimar_fault_build_id, 16) != 0)
            vimar_alloc_trace_retained_status |= 4u;
    }
    for (unsigned i = 0; i < 3; ++i) {
        vimar_alloc_trace_previous[i][0] = 32;
        memcpy(vimar_alloc_trace_previous[i] + 1, raw + 32 * i, 32);
    }
    retained_slot = previous ? latest_slot ^ 1u : 0;
    retained_boot = boot_sequence;
    retained_written = false;
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    retained_ready = true;
    if (retained != 0) {
        bool cached;
        retain_failure(&history[(total - 1u) % VIMAR_ALLOC_TRACE_CAPACITY], trace_now(&cached), true);
    }
    irq_unlock(key);
}

static void retain_failure(const struct vimar_alloc_failure *record, uint32_t now, bool force)
{
    if (!retained_ready) return;
    if (retained_busy) { (void)__atomic_fetch_or(&vimar_alloc_trace_retained_status, 16u, __ATOMIC_RELAXED); return; }
    if (retained_written && retained_sequence == record->sequence) return;
    if (!force && retained_written && (uint32_t)(now - retained_at) < 1000u) {
        (void)__atomic_fetch_or(&vimar_alloc_trace_retained_status, 8u, __ATOMIC_RELAXED);
        return;
    }
    retained_busy = true;
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    struct retained_failure saved = {
        .magic = UINT32_C(0x414c4c43), .version = 1,
        .generation = ++retained_generation, .boot = retained_boot,
        .record = *record, .commit = UINT32_C(0x41545243),
    };
    memcpy(saved.build_id, vimar_fault_build_id, 16);
    saved.crc = retained_crc((const uint8_t *)&saved);
    uint32_t words[22];
    memcpy(words, &saved, sizeof(saved));
    volatile uint32_t *destination = ALLOC_RETAINED + retained_slot * 32;
    destination[21] = 0;
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    for (unsigned i = 0; i < 21; ++i) destination[i] = words[i];
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    destination[21] = words[21];
    retained_slot ^= 1u;
    retained_at = now;
    retained_sequence = record->sequence;
    retained_written = true;
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    retained_busy = false;
    (void)__atomic_fetch_and(&vimar_alloc_trace_retained_status, ~8u, __ATOMIC_RELAXED);
}

void vimar_alloc_trace_flush(void)
{
    unsigned key = irq_lock();
    if (capture_busy || retained_busy) {
        (void)__atomic_fetch_or(&vimar_alloc_trace_retained_status, 16u, __ATOMIC_RELAXED);
    } else {
        capture_busy = true;
        __atomic_thread_fence(__ATOMIC_SEQ_CST);
        if (retained != 0) {
            bool cached;
            uint32_t now = trace_now(&cached);
            struct vimar_alloc_failure completed = history[(total - 1u) % VIMAR_ALLOC_TRACE_CAPACITY];
            retain_failure(&completed, now, true);
        }
        __atomic_thread_fence(__ATOMIC_SEQ_CST);
        capture_busy = false;
    }
    irq_unlock(key);
}

static void put32(uint8_t *out, uint32_t value) { memcpy(out, &value, sizeof(value)); }

void vimar_alloc_trace_refresh(void)
{
    unsigned key = irq_lock();
    bool cached;
    (void)trace_now(&cached);
    if (capture_busy) { irq_unlock(key); return; }
    if (initialized && published == total) {
        irq_unlock(key);
        return;
    }
    capture_busy = true;
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    vimar_alloc_trace_metadata[0] = 20;
    vimar_alloc_trace_metadata[1] = 1;
    vimar_alloc_trace_metadata[2] = sizeof(struct vimar_alloc_failure);
    vimar_alloc_trace_metadata[3] = VIMAR_ALLOC_TRACE_CAPACITY;
    vimar_alloc_trace_metadata[4] = retained | (counter_wrapped ? 64u : 0u)
                                  | (history_overwritten ? 128u : 0u);
    put32(vimar_alloc_trace_metadata + 5, total);
    put32(vimar_alloc_trace_metadata + 9, overwritten);
    put32(vimar_alloc_trace_metadata + 13, missing_context);
    put32(vimar_alloc_trace_metadata + 17, total);
    vimar_alloc_trace_first[0] = vimar_alloc_trace_latest[0] = sizeof(struct vimar_alloc_failure);
    memcpy(vimar_alloc_trace_first + 1, &first_record, sizeof(first_record));
    if (retained != 0)
        memcpy(vimar_alloc_trace_latest + 1, &history[(total - 1u) % VIMAR_ALLOC_TRACE_CAPACITY], sizeof(first_record));
    for (unsigned i = 0; i < VIMAR_ALLOC_TRACE_CAPACITY; ++i) {
        vimar_alloc_trace_history[i][0] = sizeof(struct vimar_alloc_failure);
        memcpy(vimar_alloc_trace_history[i] + 1, &history[i], sizeof(history[i]));
    }
    for (unsigned i = 0; i < VIMAR_ALLOC_TRACE_HOLDER_CHUNKS; ++i) {
        uint8_t *out = vimar_alloc_trace_holders[i];
        memset(out, 0, 41);
        out[0] = 40;
        put32(out + 1, total);
        for (unsigned j = 0; j < 3 && i * 3 + j < VIMAR_ALLOC_TRACE_POOL; ++j)
            memcpy(out + 5 + 12 * j, &failure_holders[i * 3 + j], sizeof(failure_holders[0]));
    }
    published = total;
    initialized = true;
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    capture_busy = false;
    irq_unlock(key);
}
