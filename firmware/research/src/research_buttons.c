#include "research_buttons.h"
#include <string.h>

#define DEBOUNCE_MS 30u
#define LONG_PRESS_MS 500u
#define DIM_STEP_MS 50u
#define DIM_STEP 819
#define RECOVERY_MS 5000u

void research_buttons_init(struct research_buttons *b)
{
    memset(b, 0, sizeof(*b));
    b->last_on = 32767;
    b->blocked = true; /* Require release after boot before operating the light. */
}

void research_buttons_cancel(struct research_buttons *b)
{
    b->blocked = true;
    b->long_press = false;
}

struct research_button_action research_buttons_tick(struct research_buttons *b,
    uint32_t now, uint8_t pressed, int32_t current)
{
    struct research_button_action a = {0};
    pressed &= 3u;
    if (current != RESEARCH_LEVEL_OFF) { b->last_on = current; }
    if (!b->initialized) {
        b->initialized = true;
        b->raw = pressed;
        b->raw_since = now;
    }
    if (pressed != b->raw) {
        if (pressed == 0 && (b->stable == RESEARCH_BUTTON_UP ||
                            b->stable == RESEARCH_BUTTON_DOWN) &&
            (uint32_t)(now - b->pressed_since) >= LONG_PRESS_MS) {
            b->long_press = true; /* Release cannot turn a long gesture into a click. */
        }
        b->raw = pressed;
        b->raw_since = now;
    }
    uint8_t previous = b->stable;
    if ((uint32_t)(now - b->raw_since) >= DEBOUNCE_MS) { b->stable = b->raw; }
    bool changed = previous != b->stable;

    /* Stop dimming immediately while a release/second key is being debounced.
     * A raw second key cancels the click even if it is released quickly. */
    if (pressed == 3u) { b->blocked = true; }
    if (b->stable == 3u && pressed == 3u) {
        b->blocked = true;
        if (!b->chord) { b->chord = true; b->chord_since = now; b->recovery_sent = false; }
        if (!b->recovery_sent && (uint32_t)(now - b->chord_since) >= RECOVERY_MS) {
            a.recovery = true;
            b->recovery_sent = true;
        }
        return a;
    }
    b->chord = false;
    if (b->blocked) {
        if (b->stable == 0 && pressed == 0 &&
            (uint32_t)(now - b->raw_since) >= DEBOUNCE_MS) {
            b->blocked = false;
            b->long_press = false;
        }
        return a;
    }
    if (changed) {
        if (previous == 0 && b->stable != 0) {
            b->pressed_since = now;
            b->long_press = false;
        } else if (b->stable == 0 && previous != 0) {
            if (!b->long_press) {
                a.set_level = true;
                a.level = current == RESEARCH_LEVEL_OFF ? b->last_on : RESEARCH_LEVEL_OFF;
            }
            b->long_press = false;
            return a;
        } else {
            b->blocked = true;
            return a;
        }
    }
    if (b->stable == 0 || pressed != b->stable) { return a; }
    if ((uint32_t)(now - b->pressed_since) < LONG_PRESS_MS) { return a; }
    if (b->long_press && (uint32_t)(now - b->last_step) < DIM_STEP_MS) { return a; }
    b->long_press = true;
    b->last_step = now;
    if (b->stable == RESEARCH_BUTTON_DOWN && current == RESEARCH_LEVEL_OFF) { return a; }
    int32_t next = current == RESEARCH_LEVEL_OFF ? RESEARCH_LEVEL_MIN :
        current + (b->stable == RESEARCH_BUTTON_UP ? DIM_STEP : -DIM_STEP);
    if (next < RESEARCH_LEVEL_MIN) { next = RESEARCH_LEVEL_MIN; }
    if (next > 32767) { next = 32767; }
    if (next != current) { a.set_level = true; a.level = next; }
    return a;
}
