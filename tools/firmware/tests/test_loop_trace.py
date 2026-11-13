"""Host checks for the CI-only loop recorder frame format; no hardware I/O."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "loop_trace.h"

static unsigned stores;
void loop_trace_test_word(unsigned index) { (void)index; stores++; }

static const uint8_t BUILD[16] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16};

static void fresh(struct loop_trace *trace, volatile uint32_t *window)
{
    loop_trace_init(trace, window, BUILD, 7);
    assert(!trace->blocked && trace->sequence == 0 && trace->next_slot == 0);
}

int main(void)
{
    static volatile uint32_t window[LOOP_TRACE_WINDOW_WORDS];
    struct loop_trace trace;
    struct loop_trace_record record;
    uint32_t live[LOOP_TRACE_LIVE_WORDS];

    /* An empty window holds no frame and does not block publication. */
    assert(!loop_trace_latest(window, &record));
    fresh(&trace, window);

    /* One complete loop: every stage publishes a committed frame. */
    assert(loop_trace_event(&trace, LOOP_TRACE_ENTER, 100, 0));
    assert(loop_trace_event(&trace, LOOP_TRACE_IO_DONE, 104, 0));
    assert(loop_trace_event(&trace, LOOP_TRACE_WORK_DONE, 110, 0));
    assert(loop_trace_event(&trace, LOOP_TRACE_REARM_START, 115, 0));
    assert(loop_trace_event(&trace, LOOP_TRACE_REARM_RETURN, 118, -5));
    assert(loop_trace_event(&trace, LOOP_TRACE_ENTER, 160, 0));
    assert(stores == 6 * 33);
    assert(loop_trace_latest(window, &record));
    assert(record.version == 2 && record.length == 128 && record.sequence == 6);
    assert(record.boot_sequence == 7 && memcmp(record.build_id, BUILD, 16) == 0);
    assert(record.sample.entries == 2 && record.sample.completed == 1);
    assert(record.sample.attempts == 1 && record.sample.returns == 1);
    assert(record.sample.last_result == -5 && record.sample.first_alarm_error == -5);
    assert(record.timing.input.max_ms == 4 && record.timing.work.max_ms == 11);
    assert(record.timing.rearm.max_ms == 3 && record.timing.callback.max_ms == 18);
    assert(record.timing.wait.max_ms == 42 && record.timing.entry_gap.max_ms == 60);
    assert(record.timing.previous_stage == LOOP_TRACE_REARM_RETURN);

    /* Frames are rebuilt from zeroed storage: identical inputs give identical
     * words regardless of earlier window contents, so the CRC never depends on
     * indeterminate padding. */
    static volatile uint32_t clean[LOOP_TRACE_WINDOW_WORDS], dirty[LOOP_TRACE_WINDOW_WORDS];
    struct loop_trace first, second;
    for (unsigned i = 0; i < LOOP_TRACE_WINDOW_WORDS; i++) dirty[i] = (i % 32 == 31) ? 0 : 0xa5a5a5a5u;
    fresh(&first, clean);
    fresh(&second, dirty);
    for (unsigned step = 0; step < 2; step++) {
        enum loop_trace_stage stage = step ? LOOP_TRACE_IO_DONE : LOOP_TRACE_ENTER;
        assert(loop_trace_event(&first, stage, 100 + step, 0));
        assert(loop_trace_event(&second, stage, 100 + step, 0));
    }
    for (unsigned i = 0; i < LOOP_TRACE_WINDOW_WORDS; i++) assert(clean[i] == dirty[i]);

    /* A corrupted CRC or commit word invalidates only that slot. */
    window[32 + 30] ^= 1u;
    assert(loop_trace_latest(window, &record) && record.sequence == 5);
    window[32 + 30] ^= 1u;
    window[31] = 0;
    assert(loop_trace_latest(window, &record) && record.sequence == 6);

    /* An existing frame blocks publication until acknowledged. */
    struct loop_trace again;
    loop_trace_init(&again, window, BUILD, 8);
    assert(again.blocked && again.sequence == 6 && again.next_slot == 0);
    assert(!loop_trace_event(&again, LOOP_TRACE_ENTER, 5, 0));
    loop_trace_acknowledge(&again);
    assert(!again.blocked && window[31] == 0 && window[63] == 0);
    assert(!loop_trace_latest(window, &record));
    assert(loop_trace_event(&again, LOOP_TRACE_ENTER, 6, 0));
    assert(loop_trace_latest(window, &record) && record.sequence == 7);

    /* Invalid stages and re-entry are refused; fatal stages freeze. */
    assert(!loop_trace_event(&again, (enum loop_trace_stage)0, 7, 0));
    again.busy = true;
    assert(!loop_trace_event(&again, LOOP_TRACE_ENTER, 7, 0));
    again.busy = false;
    assert(loop_trace_event(&again, LOOP_TRACE_SDK_FATAL, 9, -29));
    assert(again.frozen && !loop_trace_event(&again, LOOP_TRACE_ENTER, 10, 0));
    assert(loop_trace_latest(window, &record) && record.sample.last_result == -29);

    loop_trace_live(&again, live);
    assert(live[0] == 1 && live[1] == 8 && live[2] == 8 && live[3] == 2);
    return 0;
}
'''


def test_loop_trace_frames_rotate_validate_and_block(tmp_path):
    source = tmp_path / 'test.c'
    source.write_text(HARNESS)
    binary = tmp_path / 'test'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-DLOOP_TRACE_TEST',
                    '-I', str(ROOT / 'firmware/src'), str(source),
                    str(ROOT / 'firmware/src/loop_trace.c'), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
