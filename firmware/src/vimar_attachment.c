#include "vimar_attachment.h"

/* Stock Zigbee accepts a rising edge after at least 99 RTC ticks LOW.
 * An isolated qualified pulse is not a held button: require a stable train.
 * 30 ms bridges both 50/60 Hz cycle gaps; 40 ms filters train start/end.
 * These application timings are candidates, not measured terminal timings. */
#define MIN_LOW_TICKS 99U
#define TRAIN_GAP_TICKS 983U
#define DEBOUNCE_MS 40U
#define MAX_POLL_GAP_MS 125U

void vimar_attachment_edge(struct vimar_attachment_capture *c, bool high,
    uint32_t now_ticks)
{
    if (!high) {
        if (!c->have_low) {
            c->low_since = now_ticks;
            c->have_low = true;
        }
        return;
    }
    if (c->have_low && now_ticks - c->low_since >= MIN_LOW_TICKS) {
        c->have_pulse = true;
        c->last_pulse = now_ticks;
        c->pulses++;
    }
    c->have_low = false;
}

struct vimar_attachment_sample vimar_attachment_tick(struct vimar_attachment_input *s,
    const struct vimar_attachment_capture *c, uint32_t now_ticks, uint64_t now_ms)
{
    struct vimar_attachment_sample sample = {0};
    bool raw = c->have_pulse && now_ticks - c->last_pulse <= TRAIN_GAP_TICKS;
    if (!s->initialized || now_ms - s->last_poll_ms > MAX_POLL_GAP_MS) {
        sample.cancel = s->initialized;
        s->initialized = true;
        s->enabled = false;
        s->pressed = false;
        s->raw = raw;
        s->raw_since_ms = now_ms;
    }
    s->last_poll_ms = now_ms;
    if (s->raw != raw) {
        s->raw = raw;
        s->raw_since_ms = now_ms;
    }
    if (!s->enabled) {
        if (!raw && now_ms - s->raw_since_ms >= DEBOUNCE_MS) {
            s->enabled = true;
        }
    } else if (raw != s->pressed && now_ms - s->raw_since_ms >= DEBOUNCE_MS) {
        s->pressed = raw;
        sample.changed = true;
        sample.edge_ms = s->raw_since_ms;
    }
    sample.pressed = s->pressed;
    sample.settled = s->enabled && raw == s->pressed;
    return sample;
}
