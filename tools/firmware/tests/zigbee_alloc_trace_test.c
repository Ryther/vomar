/* Host-only boundaries; the recorder and getter interposition are real C. */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "zigbee_alloc_trace.h"
#include "zboss_api.h"

static uint32_t now = 1000;
volatile uint32_t synthetic_retained[64];
static uintptr_t thread = 1;
static unsigned irq_depth, mode, recursion;
static bool isr, inject_capture, inject_clock;
static struct vimar_alloc_pool_state pool = {.out = 18, .pool_size = 40, .queue_used = 3,
    .head = 0x12345, .tail = 0x23457, .valid = 3, .bitmap = {0xff, 0xff, 3}};
unsigned irq_lock(void) { return irq_depth++; }
void irq_unlock(unsigned key) { assert(irq_depth == key + 1); irq_depth = key; }
void *k_current_get(void) { return (void *)thread; }
bool k_is_in_isr(void) { return isr; }
uint32_t k_uptime_get_32(void) {
    assert(!isr);
    if (inject_clock) { inject_clock = false; vimar_alloc_trace_failure(); }
    return now;
}
void vimar_alloc_trace_pool_snapshot(struct vimar_alloc_pool_state *out) {
    if (inject_capture) {
        inject_capture = false;
        vimar_alloc_trace_failure();
        vimar_alloc_trace_storage_result(1, 2);
        vimar_alloc_trace_release(1);
    }
    *out = pool;
}

zb_bufid_t zb_buf_get_func(zb_bool_t, zb_uint_t);
zb_bufid_t vimar_sdk_buf_get_func(zb_bool_t direction, zb_uint_t size)
{
    (void)direction;
    if (mode == 1) vimar_alloc_trace_storage_result(8, 0);
    if (mode == 2) { vimar_alloc_trace_storage_result(8, 1); return 1; }
    if (mode == 3 && !recursion) {
        recursion++;
        assert(zb_buf_get_func(1, 37) == 0);
        recursion--;
    }
    if (mode == 4 && recursion < 4) {
        recursion++; thread++;
        assert(zb_buf_get_func(1, size + 1) == 0);
        thread--; recursion--;
    }
    vimar_alloc_trace_failure();
    return 0;
}

static uint32_t word(const uint8_t *data) {
    return (uint32_t)data[0] | (uint32_t)data[1]<<8 | (uint32_t)data[2]<<16 | (uint32_t)data[3]<<24;
}
static struct vimar_alloc_failure latest(void) {
    vimar_alloc_trace_refresh();
    struct vimar_alloc_failure result;
    memcpy(&result, vimar_alloc_trace_latest + 1, sizeof(result));
    return result;
}
bool vimar_alloc_trace_delayed_snapshot(uint8_t dir, struct vimar_alloc_delayed_queue *out)
{ (void)dir; memset(out, 0, sizeof(*out)); return false; }
zb_bufid_t vimar_sdk_zb_buf_get_hipri_func(zb_bool_t dir)
{ return vimar_sdk_buf_get_func(dir, 0); }
zb_ret_t vimar_sdk_zb_buf_get_out_delayed_func(zb_callback_t cb) { (void)cb; return -1; }
zb_ret_t vimar_sdk_zb_buf_get_in_delayed_func(zb_callback_t cb) { (void)cb; return -1; }
zb_ret_t vimar_sdk_zb_buf_get_out_delayed_ext_func(zb_callback2_t cb,zb_uint16_t arg,zb_uint_t size)
{ (void)cb; (void)arg; (void)size; return -1; }
zb_ret_t vimar_sdk_zb_buf_get_in_delayed_ext_func(zb_callback2_t cb,zb_uint16_t arg,zb_uint_t size)
{ (void)cb; (void)arg; (void)size; return -1; }
zb_bool_t vimar_sdk_process_delayed_buf_entry_unsafe(void *entry,zb_bool_t dir)
{ (void)entry; (void)dir; return 0; }
int main(int argc, char **argv)
{
    assert(argc == 2 || argc == 3);
    if (!strcmp(argv[1], "retained_write")) {
        vimar_alloc_trace_boot(31);
        assert(zb_buf_get_func(1, 1216) == 0);
        now++;
        assert(zb_buf_get_func(0, 44) == 0);
        vimar_alloc_trace_flush();
        FILE *f = fopen(argv[2], "wb"); assert(f);
        assert(fwrite((const void *)synthetic_retained, 1, 256, f) == 256);
        assert(fclose(f) == 0); return 0;
    }
    if (!strncmp(argv[1], "retained_read", 13)) {
        FILE *f = fopen(argv[2], "rb"); assert(f);
        assert(fread((void *)synthetic_retained, 1, 256, f) == 256);
        assert(fclose(f) == 0);
        vimar_alloc_trace_boot(32);
        bool empty = !strcmp(argv[1], "retained_read_empty");
        assert((vimar_alloc_trace_retained_status & 2) == (empty ? 0 : 2));
        if (!empty) {
            uint8_t raw[96];
            for (unsigned i = 0; i < 3; ++i) memcpy(raw + 32*i, vimar_alloc_trace_previous[i]+1, 32);
            assert(word(raw + 12) == 31);
            struct vimar_alloc_failure record; memcpy(&record, raw + 32, sizeof(record));
            assert(record.sequence == (!strcmp(argv[1], "retained_read_fallback") ? 1u : 2u));
            assert(record.requested_bytes == (record.sequence == 1 ? 1216u : 44u));
            bool foreign = !strcmp(argv[1], "retained_read_foreign");
            assert((vimar_alloc_trace_retained_status & 4) == (foreign ? 4 : 0));
            assert(raw[16] == (foreign ? 0xaa : 0x55));
        }
        vimar_alloc_trace_refresh();
        assert(word(vimar_alloc_trace_metadata + 5) == 0);
        return 0;
    }
    if (!strcmp(argv[1], "storage")) mode = 1;
    if (!strcmp(argv[1], "nested_flush")) {
        vimar_alloc_trace_boot(31);
        assert(zb_buf_get_func(1, 1216) == 0);
        now += 2000;
        inject_clock = true;
        vimar_alloc_trace_flush();
        assert(latest().sequence == 1 && vimar_alloc_trace_dropped == 1);
        return 0;
    }
    if (!strcmp(argv[1], "isr") || !strcmp(argv[1], "isr_holder")) {
        if (!strcmp(argv[1], "isr_holder")) {
            mode = 2; assert(zb_buf_get_func(0, 1216) == 1); mode = 0;
        }
        vimar_alloc_trace_refresh();
        now += 100;
        isr = true;
        assert(zb_buf_get_func(1, 1216) == 0);
        isr = false;
        struct vimar_alloc_failure record = latest();
        assert(record.time_ms == 1000 && (record.flags & 16));
        assert(vimar_alloc_trace_dropped == 0);
        if (!strcmp(argv[1], "isr_holder")) assert(vimar_alloc_trace_holders[0][16] & 4);
        return 0;
    }
    if (!strcmp(argv[1], "nested_capture")) {
        inject_capture = true;
        assert(zb_buf_get_func(1, 1216) == 0);
        struct vimar_alloc_failure record = latest();
        assert(record.sequence == 1 && vimar_alloc_trace_dropped == 1);
        assert(vimar_alloc_trace_lifetime_gaps == 2 && (record.valid & 32));
        assert((record.flags & 12) == 0);
        return 0;
    }
    if (!strcmp(argv[1], "holders") || !strcmp(argv[1], "clock_wrap")) {
        mode = 2;
        if (!strcmp(argv[1], "clock_wrap")) now = UINT32_MAX - 10;
        assert(zb_buf_get_func(0, 1216) == 1);
        now += 50;
        mode = 0;
        assert(zb_buf_get_func(1, 10) == 0);
        struct vimar_alloc_failure record = latest();
        assert(record.oldest_id == 1 && record.oldest_units == 8 && record.oldest_age_ms == 50);
        assert(record.oldest_caller != 0);
        assert(word(vimar_alloc_trace_holders[0] + 1) == 1);
        assert(vimar_alloc_trace_holders[0][13] == 1);
        vimar_alloc_trace_release(1);
        assert(zb_buf_get_func(1, 10) == 0);
        assert(latest().oldest_id == 0);
    } else if (!strcmp(argv[1], "nested")) {
        mode = 3;
        assert(zb_buf_get_func(0, 21) == 0);
        struct vimar_alloc_failure record = latest();
        assert(record.sequence == 2 && record.requested_bytes == 21 && !(record.flags & 1));
        struct vimar_alloc_failure inner;
        memcpy(&inner, vimar_alloc_trace_history[0] + 1, sizeof(inner));
        assert(inner.requested_bytes == 37 && (inner.flags & 3) == 3);
    } else if (!strcmp(argv[1], "contexts")) {
        mode = 4;
        assert(zb_buf_get_func(0, 21) == 0);
        struct vimar_alloc_failure record = latest();
        assert(record.sequence == 5 && record.requested_bytes == 21);
        assert(word(vimar_alloc_trace_metadata + 13) == 1);
    } else if (!strcmp(argv[1], "missing")) {
        vimar_alloc_trace_failure();
        struct vimar_alloc_failure record = latest();
        assert(record.sequence == 1 && !(record.flags & 2) && record.caller == 0);
        assert(word(vimar_alloc_trace_metadata + 13) == 1);
    } else if (!strcmp(argv[1], "history")) {
        for (unsigned i = 0; i < 35; ++i) assert(zb_buf_get_func(0, i + 1) == 0);
        struct vimar_alloc_failure record = latest();
        assert(record.sequence == 35 && record.requested_bytes == 35);
        assert(word(vimar_alloc_trace_first + 1) == 1);
        assert(word(vimar_alloc_trace_metadata + 9) == 3);
        assert((vimar_alloc_trace_metadata[4] & 63) == 32 && (vimar_alloc_trace_metadata[4] & 128));
        assert(word(vimar_alloc_trace_history[2] + 1) == 35);
        assert(word(vimar_alloc_trace_history[3] + 1) == 4);
    } else {
        assert(zb_buf_get_func(1, 1216) == 0);
        struct vimar_alloc_failure record = latest();
        assert(record.sequence == 1 && record.caller != 0 && record.requested_bytes == 1216);
        assert((record.flags & 3) == 3 && record.out == 18 && record.in == 0);
        assert(record.queue_used == 3 && record.head == 0x12345 && record.tail == 0x23457);
        assert(record.bitmap[0] == 0xff && record.bitmap[2] == 3);
        assert((record.flags & 12) == (mode == 1 ? 12 : 0));
        assert(record.units == (mode == 1 ? 8 : 0));
    }
    assert(irq_depth == 0);
    puts("PASS: bounded allocation capture; no flash/radio/allocator boundary linked");
    return 0;
}
