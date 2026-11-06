#ifndef VIMAR_LOOP_TRACE_H
#define VIMAR_LOOP_TRACE_H
#include <stdbool.h>
#include <stdint.h>

#define LOOP_TRACE_WINDOW_WORDS 64u
#define LOOP_TRACE_LIVE_WORDS 11u
enum loop_trace_stage {
    LOOP_TRACE_ENTER = 1, LOOP_TRACE_IO_DONE, LOOP_TRACE_WORK_DONE,
    LOOP_TRACE_REARM_START, LOOP_TRACE_REARM_RETURN,
    LOOP_TRACE_RECOVERY, LOOP_TRACE_KERNEL_FATAL, LOOP_TRACE_SDK_FATAL
};
struct loop_trace_sample {
    uint32_t entries, completed, attempts, returns;
    int32_t last_result, first_alarm_error;
    uint32_t stage, uptime_ms;
};
struct loop_trace_peak {
    uint32_t max_ms, at_uptime_ms;
};
struct loop_trace_timing {
    struct loop_trace_peak entry_gap, callback, wait, input, work, rearm;
    uint32_t previous_stage, previous_age_ms;
};
struct loop_trace_record {
    uint32_t magic;
    uint16_t version, length;
    uint32_t sequence, boot_sequence;
    uint8_t build_id[16];
    struct loop_trace_sample sample;
    struct loop_trace_timing timing;
    uint32_t crc, commit;
};
struct loop_trace {
    volatile uint32_t *window;
    uint8_t build_id[16];
    uint32_t boot_sequence, sequence, next_slot;
    struct loop_trace_sample sample;
    struct loop_trace_timing timing;
    uint32_t entry_ms, io_ms;
    bool blocked, busy, frozen, have_entry, have_io;
};
/* Caller serializes updates with saved/restored IRQ state. Init is read-only;
 * any complete old frame blocks publication until durable readback and ack. */
void loop_trace_init(struct loop_trace *, volatile uint32_t *, const uint8_t[16], uint32_t);
bool loop_trace_latest(const volatile uint32_t *, struct loop_trace_record *);
bool loop_trace_event(struct loop_trace *, enum loop_trace_stage, uint32_t, int32_t);
void loop_trace_acknowledge(struct loop_trace *);
void loop_trace_live(const struct loop_trace *, uint32_t[LOOP_TRACE_LIVE_WORDS]);
#endif
