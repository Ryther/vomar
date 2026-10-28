#ifndef VIMAR_ATTACHMENT_H
#define VIMAR_ATTACHMENT_H

#include <stdbool.h>
#include <stdint.h>

/* Timestamp units match the pinned nRF RTC clock, 32768 ticks per second.
 * Capture is ISR-owned; the adapter snapshots it under its spinlock. */
struct vimar_attachment_capture {
    bool have_low, have_pulse;
    uint32_t low_since, last_pulse, pulses;
};

struct vimar_attachment_input {
    bool initialized, enabled, raw, pressed;
    uint64_t last_poll_ms, raw_since_ms;
};

struct vimar_attachment_sample {
    bool changed, pressed, settled, cancel;
    uint64_t edge_ms;
};

void vimar_attachment_edge(struct vimar_attachment_capture *, bool high,
    uint32_t now_ticks);
struct vimar_attachment_sample vimar_attachment_tick(struct vimar_attachment_input *,
    const struct vimar_attachment_capture *, uint32_t now_ticks, uint64_t now_ms);

#endif
