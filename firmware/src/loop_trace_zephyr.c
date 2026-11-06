#include "loop_trace_zephyr.h"
#include <zephyr/kernel.h>
#include <zephyr/settings/settings.h>
#include <errno.h>
#include <string.h>
#include VIMAR_FAULT_BUILD_ID_HEADER

#ifndef LOOP_RETAINED
#include <zephyr/devicetree.h>
_Static_assert(DT_REG_ADDR(DT_NODELABEL(sram0)) == UINT32_C(0x20000000) &&
               DT_REG_SIZE(DT_NODELABEL(sram0)) <= UINT32_C(0x3fd00),
               "Loop trace requires its reserved SRAM overlay");
/* shortcut: legacy loader/REC free heaps may overwrite this RAM; qualify the
 * exact transition before relying on retention. CRC rejects damaged frames. */
#define LOOP_RETAINED ((volatile uint32_t *)UINT32_C(0x2003fd00))
#endif
static struct loop_trace trace;
static bool ready;
uint8_t vimar_loop_trace_current[45], vimar_loop_trace_previous[4][33];
uint32_t vimar_loop_trace_status;

void vimar_loop_trace_boot(uint32_t boot_sequence)
{
    struct loop_trace_record previous, retained;
    uint32_t saved[64] = {0};
    loop_trace_init(&trace, LOOP_RETAINED, vimar_fault_build_id, boot_sequence);
    ssize_t size = settings_load_one("vimar/loop_trace", saved, 128);
    bool durable = size == 128 && loop_trace_latest(saved, &previous);
    uint32_t status = durable ? 6u : 0u;
    if (size < 0 && size != -ENOENT) status |= 8u;
    bool have_previous = durable;
    if (loop_trace_latest(LOOP_RETAINED, &retained)) {
        bool same = durable && memcmp(&previous, &retained, 128) == 0;
        previous = retained;
        have_previous = true;
        status = 2u;
        if (same || settings_save_one("vimar/loop_trace", &retained, 128) == 0) {
            size = settings_load_one("vimar/loop_trace", saved, 128);
            if (size == 128 && memcmp(saved, &retained, 128) == 0) {
                status |= 4u;
                loop_trace_acknowledge(&trace);
            } else status |= 8u;
        } else status |= 8u;
    }
    for (unsigned i = 0; i < 4; i++) {
        vimar_loop_trace_previous[i][0] = 32;
        memset(vimar_loop_trace_previous[i] + 1, 0, 32);
        if (have_previous) memcpy(vimar_loop_trace_previous[i] + 1, (uint8_t *)&previous + i * 32, 32);
    }
    if (have_previous && memcmp(previous.build_id, vimar_fault_build_id, 16)) status |= 32u;
    vimar_loop_trace_status = status | (trace.blocked ? 16u : 1u);
    vimar_loop_trace_current[0] = 44;
    uint32_t live[LOOP_TRACE_LIVE_WORDS];
    loop_trace_live(&trace, live);
    memcpy(vimar_loop_trace_current + 1, live, sizeof live);
    ready = true;
}

void vimar_loop_trace_event(enum loop_trace_stage stage, int32_t result)
{
    if (!ready) return;
    unsigned key = irq_lock();
    /* Zero-latency radio IRQs remain enabled; a nested fatal keeps the last
     * committed frame rather than exporting an interrupted update. */
    if (!trace.busy) {
        (void)loop_trace_event(&trace, stage, k_uptime_get_32(), result);
        uint32_t live[LOOP_TRACE_LIVE_WORDS];
        loop_trace_live(&trace, live);
        memcpy(vimar_loop_trace_current + 1, live, sizeof live);
    }
    irq_unlock(key);
}
