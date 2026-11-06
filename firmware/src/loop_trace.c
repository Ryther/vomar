#include "loop_trace.h"
#include <stddef.h>
#include <string.h>

#if __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "Loop trace format requires little endian"
#endif
#define MAGIC UINT32_C(0x4c545243)
#define COMMIT UINT32_C(0x434f4d54)
_Static_assert(sizeof(struct loop_trace_record) == 128, "loop record ABI");
_Static_assert(sizeof(struct loop_trace_sample) == 32, "loop sample ABI");
_Static_assert(sizeof(struct loop_trace_timing) == 56, "loop timing ABI");
_Static_assert(offsetof(struct loop_trace_record, timing) == 64, "loop timing offset");
_Static_assert(offsetof(struct loop_trace_record, crc) == 120, "loop CRC ABI");
_Static_assert(offsetof(struct loop_trace_record, build_id) == 16, "loop build ABI");

static uint32_t crc32(const uint8_t *data, size_t size)
{
    uint32_t crc = UINT32_MAX;
    for (size_t i = 0; i < size; i++) {
        crc ^= data[i];
        for (unsigned b = 0; b < 8; b++) crc = (crc >> 1) ^ ((crc & 1) ? UINT32_C(0xedb88320) : 0);
    }
    return ~crc;
}

static bool read_slot(const volatile uint32_t *window, unsigned slot, struct loop_trace_record *record)
{
    uint32_t words[32];
    for (unsigned i = 0; i < 32; i++) words[i] = window[slot * 32 + i];
    memcpy(record, words, sizeof *record);
    if (record->magic != MAGIC || (record->version != 1 && record->version != 2) || record->length != 128 ||
        record->commit != COMMIT || !record->sequence ||
        record->sample.stage < LOOP_TRACE_ENTER || record->sample.stage > LOOP_TRACE_SDK_FATAL ||
        record->crc != crc32((const uint8_t *)record, 120)) return false;
    if (record->version == 1) {
        const uint8_t *reserved = (const uint8_t *)&record->timing;
        for (unsigned i = 0; i < sizeof record->timing; i++) if (reserved[i]) return false;
    } else if (record->timing.previous_stage > LOOP_TRACE_SDK_FATAL) return false;
    return true;
}

bool loop_trace_latest(const volatile uint32_t *window, struct loop_trace_record *record)
{
    struct loop_trace_record first, second;
    bool a = read_slot(window, 0, &first), b = read_slot(window, 1, &second);
    if (!a && !b) return false;
    uint32_t delta = second.sequence - first.sequence;
    *record = b && (!a || (delta && delta < UINT32_C(0x80000000))) ? second : first;
    return true;
}

void loop_trace_init(struct loop_trace *trace, volatile uint32_t *window, const uint8_t build[16], uint32_t boot)
{
    *trace = (struct loop_trace){.window = window, .boot_sequence = boot};
    memcpy(trace->build_id, build, 16);
    struct loop_trace_record record;
    trace->blocked = loop_trace_latest(window, &record);
    if (trace->blocked) {
        trace->sequence = record.sequence;
        struct loop_trace_record first;
        trace->next_slot = read_slot(window, 0, &first) && first.sequence == record.sequence ? 1 : 0;
    }
}

static void store(volatile uint32_t *word, uint32_t value, unsigned index)
{
    *word = value;
#ifdef LOOP_TRACE_TEST
    extern void loop_trace_test_word(unsigned);
    loop_trace_test_word(index);
#else
    (void)index;
#endif
}

static void peak(struct loop_trace_peak *value, uint32_t duration, uint32_t now)
{
    if (duration > value->max_ms) {
        value->max_ms = duration;
        value->at_uptime_ms = now;
    }
}

static void measure(struct loop_trace *trace, enum loop_trace_stage stage, uint32_t now)
{
    /* Unsigned elapsed intervals must be shorter than one49.7-day uptime wrap. */
    struct loop_trace_timing *timing = &trace->timing;
    uint32_t previous = trace->sample.stage;
    uint32_t age = previous ? now - trace->sample.uptime_ms : 0;
    timing->previous_stage = previous;
    timing->previous_age_ms = age;
    if (stage == LOOP_TRACE_ENTER) {
        if (trace->have_entry) peak(&timing->entry_gap, now - trace->entry_ms, now);
        if (previous == LOOP_TRACE_REARM_RETURN) peak(&timing->wait, age, now);
        trace->entry_ms = now;
        trace->have_entry = true;
        trace->have_io = false;
    } else if (stage == LOOP_TRACE_IO_DONE && trace->have_entry) {
        peak(&timing->input, now - trace->entry_ms, now);
        trace->io_ms = now;
        trace->have_io = true;
    } else if (stage == LOOP_TRACE_REARM_START && trace->have_io) {
        peak(&timing->work, now - trace->io_ms, now);
    } else if (stage == LOOP_TRACE_REARM_RETURN) {
        if (previous == LOOP_TRACE_REARM_START) peak(&timing->rearm, age, now);
        if (trace->have_entry) peak(&timing->callback, now - trace->entry_ms, now);
    }
}

bool loop_trace_event(struct loop_trace *trace, enum loop_trace_stage stage, uint32_t now, int32_t result)
{
    if (trace->busy || trace->frozen || stage < LOOP_TRACE_ENTER || stage > LOOP_TRACE_SDK_FATAL) return false;
    trace->busy = true;
    measure(trace, stage, now);
    struct loop_trace_sample *sample = &trace->sample;
    sample->stage = (uint32_t)stage;
    sample->uptime_ms = now;
    if (stage == LOOP_TRACE_ENTER) sample->entries++;
    if (stage == LOOP_TRACE_WORK_DONE) sample->completed++;
    if (stage == LOOP_TRACE_REARM_START) sample->attempts++;
    if (stage == LOOP_TRACE_REARM_RETURN) {
        sample->returns++;
        sample->last_result = result;
        if (result && !sample->first_alarm_error) sample->first_alarm_error = result;
    }
    if (stage == LOOP_TRACE_KERNEL_FATAL || stage == LOOP_TRACE_SDK_FATAL) sample->last_result = result;
    bool published = false;
    if (!trace->blocked) {
        struct loop_trace_record record = {.magic = MAGIC, .version = 2, .length = 128,
            .boot_sequence = trace->boot_sequence, .sample = *sample,
            .timing = trace->timing, .commit = COMMIT};
        if (++trace->sequence == 0) trace->sequence = 1;
        record.sequence = trace->sequence;
        memcpy(record.build_id, trace->build_id, 16);
        record.crc = crc32((const uint8_t *)&record, 120);
        uint32_t words[32];
        memcpy(words, &record, sizeof words);
        volatile uint32_t *target = trace->window + trace->next_slot * 32;
        store(target + 31, 0, 0);
        for (unsigned i = 0; i < 31; i++) store(target + i, words[i], i + 1);
        store(target + 31, COMMIT, 32);
        trace->next_slot ^= 1;
        published = true;
    }
    if (stage == LOOP_TRACE_RECOVERY || stage == LOOP_TRACE_KERNEL_FATAL || stage == LOOP_TRACE_SDK_FATAL) trace->frozen = true;
    trace->busy = false;
    return published;
}

void loop_trace_acknowledge(struct loop_trace *trace)
{
    /* A reset between stores must leave the newest durable frame in RAM. */
    store(trace->window + trace->next_slot * 32 + 31, 0, 33);
    store(trace->window + (trace->next_slot ^ 1) * 32 + 31, 0, 34);
    trace->blocked = false;
}

void loop_trace_live(const struct loop_trace *trace, uint32_t out[LOOP_TRACE_LIVE_WORDS])
{
    out[0] = 1;
    out[1] = trace->boot_sequence;
    out[2] = trace->sequence;
    memcpy(out + 3, &trace->sample, sizeof trace->sample);
}
