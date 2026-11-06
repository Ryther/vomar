/* Host-only boundary fixtures. No SDK binary or ARM code executes here. */
#include <assert.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdatomic.h>
#include <sched.h>
#include <stdlib.h>
#include <string.h>
#include "zigbee_diag_batch.h"
#include "zb_common.h"
#include "zb_scheduler.h"

struct synthetic_diagnostics synthetic_diagnostics;
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static _Thread_local unsigned depth;
static zb_callback_t callbacks[32];
static uint8_t parameters[32];
static unsigned queued, native_calls, checkpoints, foreign_calls;
static int schedule_result;
static bool inject_enqueue, inject_delivery, unexpected_dataset;
static unsigned foreign_order[4];
static atomic_bool producers_done;
static zb_time_t now, alarm_at;
static zb_callback_t alarm_callback;
static int alarm_result;
static zb_time_t checkpoint_duration;

void zb_osif_abort(void) { abort(); }

zb_time_t zb_timer_get(void) { assert(depth == 0); return now; }
zb_ret_t zb_schedule_alarm(zb_callback_t callback, zb_uint8_t parameter, zb_time_t delay)
{
    assert(depth == 0 && parameter == 0 && delay > 0 && delay <= ZB_TIME_ONE_SECOND);
    if (alarm_result != RET_OK) return alarm_result;
    assert(alarm_callback == NULL);
    alarm_callback = callback;
    alarm_at = now + delay;
    return RET_OK;
}

unsigned irq_lock(void)
{
    unsigned key = depth;
    if (depth++ == 0) assert(pthread_mutex_lock(&mutex) == 0);
    return key;
}

void irq_unlock(unsigned key)
{
    assert(depth == key + 1);
    depth = key;
    if (depth == 0) assert(pthread_mutex_unlock(&mutex) == 0);
}

zb_ret_t __real_zb_schedule_callback(zb_callback_t callback, zb_uint8_t parameter)
{
    if (inject_enqueue) {
        inject_enqueue = false;
        assert(vimar_diag_batch_schedule(0) == RET_OK);
    }
    unsigned key = irq_lock();
    int result = schedule_result;
    if (result == RET_OK) {
        assert(queued < 32);
        callbacks[queued] = callback;
        parameters[queued++] = parameter;
    }
    irq_unlock(key);
    return result;
}

void vimar_sdk_buf_diag_handle_alloc_failure(zb_uint8_t parameter)
{
    assert(parameter == 0 && depth == 0);
    ++native_calls;
    ++synthetic_diagnostics.diagnostics_info.packet_buffer_allocate_failures;
    if (inject_delivery) {
        inject_delivery = false;
        for (unsigned i = 0; i < 3; ++i) assert(vimar_diag_batch_schedule(0) == RET_OK);
    }
    assert(vimar_diag_statistics_checkpoint(unexpected_dataset ? (zb_nvram_dataset_types_t)1 : ZB_NVRAM_ZDO_DIAGNOSTICS_DATA) == RET_OK);
    ++checkpoints;
    now += checkpoint_duration;
}

static void foreign(zb_uint8_t parameter)
{
    assert(depth == 0 && foreign_calls < 4);
    foreign_order[foreign_calls++] = parameter;
}

static bool dispatch_one(void)
{
    unsigned key = irq_lock();
    if (!queued) {
        irq_unlock(key);
        if (alarm_callback == NULL) return false;
        zb_callback_t callback = alarm_callback;
        alarm_callback = NULL;
        now = alarm_at; /* Explicit synthetic clock step; no wall-clock waiting. */
        callback(0);
        return true;
    }
    zb_callback_t callback = callbacks[0];
    uint8_t parameter = parameters[0];
    --queued;
    memmove(callbacks, callbacks + 1, queued * sizeof(*callbacks));
    memmove(parameters, parameters + 1, queued * sizeof(*parameters));
    irq_unlock(key);
    callback(parameter);
    return true;
}

static void failures(unsigned count)
{
    for (unsigned i = 0; i < count; ++i) assert(vimar_diag_batch_schedule(0) == RET_OK);
}

static void *producer(void *argument)
{
    failures(*(unsigned *)argument);
    return NULL;
}

static void *consumer(void *argument)
{
    (void)argument;
    while (!atomic_load(&producers_done)) {
        (void)dispatch_one();
        sched_yield();
    }
    while (dispatch_one()) {}
    return NULL;
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    const char *mode = argv[1];
    unsigned expected = 0;
    unsigned expected_checkpoints = 1;
    synthetic_diagnostics.diagnostics_info.packet_buffer_allocate_failures = 65530;
    if (!strcmp(mode, "bounded_checkpoint")) {
        checkpoint_duration = 5;
        failures(4); assert(dispatch_one() && checkpoints == 1);
        assert(now == checkpoint_duration);
        now += 5;
        failures(8);
        assert(__real_zb_schedule_callback(foreign, 19) == RET_OK);
        assert(dispatch_one());
        assert(checkpoints == 1 && alarm_callback != NULL && queued == 1);
        assert(dispatch_one() && foreign_calls == 1 && checkpoints == 1);
        assert(alarm_at - now == ZB_TIME_ONE_SECOND - 5);
        expected = 12; expected_checkpoints = 2;
    } else if (!strcmp(mode, "timer_wrap")) {
        now = UINT32_MAX - 4;
        failures(1); assert(dispatch_one());
        now += 10;
        failures(2); assert(dispatch_one());
        assert(checkpoints == 1 && alarm_callback != NULL);
        assert(alarm_at - now == ZB_TIME_ONE_SECOND - 10);
        expected = 3; expected_checkpoints = 2;
    } else if (!strcmp(mode, "long_idle")) {
        failures(1); assert(dispatch_one());
        now += UINT32_C(0x80000010);
        failures(2); assert(dispatch_one());
        assert(checkpoints == 2 && alarm_callback == NULL);
        expected = 3; expected_checkpoints = 2;
    } else if (!strcmp(mode, "alarm_admission_fatal")) {
        failures(1); assert(dispatch_one());
        alarm_result = -17; failures(1); (void)dispatch_one(); return 99;
    } else if (!strcmp(mode, "unscheduled_delivery")) {
        failures(1); assert(dispatch_one());
        callbacks[0](0); return 99;
    } else if (!strcmp(mode, "duplicate")) { failures(4); expected = 4; assert(queued == 1); }
    else if (!strcmp(mode, "zero")) { expected_checkpoints = 0; }
    else if (!strcmp(mode, "one")) { failures(1); expected = 1; }
    else if (!strcmp(mode, "wrap65535")) { failures(65535); expected = 65535; }
    else if (!strcmp(mode, "wrap65536")) { failures(65536); expected = 65536; }
    else if (!strcmp(mode, "wrap65537")) { failures(65537); expected = 65537; }
    else if (!strcmp(mode, "wrap131073")) { failures(131073); expected = 131073; }
    else if (!strcmp(mode, "reentrant_enqueue")) {
        inject_enqueue = true; failures(1); expected = 2; assert(queued == 1);
    } else if (!strcmp(mode, "producer_during_delivery")) {
        failures(4); inject_delivery = true; expected = 7; expected_checkpoints = 2;
    } else if (!strcmp(mode, "irq_restore")) {
        unsigned key = irq_lock(); failures(4); assert(depth == 1);
        irq_unlock(key); assert(depth == 0); expected = 4;
    } else if (!strcmp(mode, "enqueue_error")) {
        schedule_result = -17; assert(vimar_diag_batch_schedule(0) == -17);
        assert(queued == 0);
        schedule_result = RET_OK; failures(1); expected = 2;
    } else if (!strcmp(mode, "reentrant_enqueue_error")) {
        schedule_result = -17; inject_enqueue = true;
        assert(vimar_diag_batch_schedule(0) == -17 && queued == 0);
        schedule_result = RET_OK; failures(1); expected = 3;
    } else if (!strcmp(mode, "foreign_fifo")) {
        assert(__real_zb_schedule_callback(foreign, 19) == RET_OK);
        failures(2);
        assert(__real_zb_schedule_callback(foreign, 27) == RET_OK);
        failures(3); expected = 5; assert(queued == 3);
    } else if (!strcmp(mode, "stats_clear_before_delivery")) {
        failures(4);
        synthetic_diagnostics.diagnostics_info.packet_buffer_allocate_failures = 0;
        expected = 4;
    } else if (!strcmp(mode, "threads") || !strcmp(mode, "threads_and_consumer")) {
        pthread_t threads[4]; unsigned count = 100003;
        pthread_t draining;
        bool concurrent_consumer = !strcmp(mode, "threads_and_consumer");
        if (concurrent_consumer) assert(pthread_create(&draining, NULL, consumer, NULL) == 0);
        for (unsigned i = 0; i < 4; ++i) assert(pthread_create(&threads[i], NULL, producer, &count) == 0);
        for (unsigned i = 0; i < 4; ++i) assert(pthread_join(threads[i], NULL) == 0);
        if (concurrent_consumer) {
            atomic_store(&producers_done, true);
            assert(pthread_join(draining, NULL) == 0);
            assert(!queued && native_calls > 0);
            expected_checkpoints = native_calls;
        } else assert(queued == 1);
        expected = 4 * count;
    } else if (!strcmp(mode, "unexpected_dataset")) {
        failures(4); unexpected_dataset = true;
    } else if (!strcmp(mode, "invalid_parameter")) {
        (void)vimar_diag_batch_schedule(1); return 99;
    } else return 2;
    struct vimar_diag_statistics before;
    vimar_diag_statistics_snapshot(&before);
    assert(before.allocation_arrivals == (inject_delivery ? expected - 3u : expected));
    if (expected == 65536) assert(before.pending == 0 && (before.status & 2u));
    if (queued || alarm_callback) assert(before.status & 2u);
    unsigned guard = 0;
    while (dispatch_one()) assert(++guard < 10);
    assert(!queued && alarm_callback == NULL && depth == 0);
    unsigned initial = !strcmp(mode, "stats_clear_before_delivery") ? 0 : 65530;
    assert(synthetic_diagnostics.diagnostics_info.packet_buffer_allocate_failures == (uint16_t)(initial + expected));
    assert(native_calls == expected_checkpoints && checkpoints == expected_checkpoints);
    struct vimar_diag_statistics after;
    vimar_diag_statistics_snapshot(&after);
    assert(after.status == 1u && after.pending == 0);
    assert(after.allocation_arrivals == expected && after.checkpoints == checkpoints);
    assert(after.sdk_allocation_failures == (uint16_t)(initial + expected));
    if (!strcmp(mode, "foreign_fifo")) {
        assert(foreign_calls == 2 && foreign_order[0] == 19 && foreign_order[1] == 27);
    }
    printf("PASS %s: modulo counter%u, native calls%u, RAM checkpoints%u\n", mode,
           synthetic_diagnostics.diagnostics_info.packet_buffer_allocate_failures, native_calls, checkpoints);
    return 0;
}
