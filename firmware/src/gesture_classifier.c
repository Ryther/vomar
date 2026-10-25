#include "gesture_classifier.h"

#include <string.h>

static uint32_t next_sequence(struct gesture_classifier *classifier)
{
    if (++classifier->next_sequence == 0) { classifier->next_sequence = 1; }
    return classifier->next_sequence;
}

static void emit(struct gesture_classifier *classifier,
    enum gesture_event_type type, enum gesture_side side,
    uint32_t sequence, uint32_t held_ms)
{
    struct gesture_event event = { .type = type, .side = side,
        .sequence_id = sequence, .held_ms = held_ms };
    classifier->callback(&event, classifier->callback_context);
}

void gesture_classifier_init(struct gesture_classifier *classifier,
    const struct dimmer_config *config, gesture_event_callback callback,
    void *callback_context)
{
    memset(classifier, 0, sizeof(*classifier));
    classifier->config = *config;
    classifier->callback = callback;
    classifier->callback_context = callback_context;
}

void gesture_classifier_edge(struct gesture_classifier *classifier,
    enum gesture_side side, bool pressed, uint64_t now_ms)
{
    if (side >= GESTURE_SIDE_COUNT || classifier->callback == NULL) { return; }
    struct gesture_side_state *state = &classifier->sides[side];
    if (pressed) {
        if (state->pressed) { return; }
        /* Resolve an expired click before a new sequence can replace or inherit it.
         * Edges can arrive while the periodic tick is paused for debounce. */
        if (state->single_pending && now_ms > state->single_deadline_ms) {
            state->single_pending = false;
            emit(classifier, GESTURE_EVENT_SINGLE, side, state->pending_sequence, 0);
        }
        state->pressed = true;
        state->long_emitted = false;
        state->pressed_at_ms = now_ms;
        state->active_sequence = next_sequence(classifier);
        state->second_press = state->single_pending &&
            now_ms <= state->single_deadline_ms;
        if (state->second_press) { state->single_pending = false; }
        emit(classifier, GESTURE_EVENT_PRESS, side, state->active_sequence, 0);
        return;
    }
    if (!state->pressed) { return; }
    state->pressed = false;
    uint64_t elapsed = now_ms - state->pressed_at_ms;
    uint32_t held_ms = elapsed > UINT32_MAX ? UINT32_MAX : (uint32_t)elapsed;
    if (state->long_emitted || elapsed >= classifier->config.long_press_ms) {
        /* A delayed LONG tick must not turn a completed hold into a click. */
        state->single_pending = false;
        state->second_press = false;
        emit(classifier, GESTURE_EVENT_RELEASE, side, state->active_sequence, held_ms);
    } else if (state->second_press) {
        emit(classifier, GESTURE_EVENT_DOUBLE, side, state->active_sequence, held_ms);
        state->second_press = false;
    } else {
        state->single_pending = true;
        state->pending_sequence = state->active_sequence;
        state->single_deadline_ms = now_ms + classifier->config.double_click_window_ms;
    }
}

void gesture_classifier_tick(struct gesture_classifier *classifier, uint64_t now_ms)
{
    for (enum gesture_side side = GESTURE_SIDE_UP; side < GESTURE_SIDE_COUNT; side++) {
        struct gesture_side_state *state = &classifier->sides[side];
        if (state->pressed && !state->long_emitted &&
            now_ms - state->pressed_at_ms >= classifier->config.long_press_ms) {
            state->long_emitted = true;
            state->single_pending = false;
            state->second_press = false;
            emit(classifier, GESTURE_EVENT_LONG, side, state->active_sequence,
                (uint32_t)(now_ms - state->pressed_at_ms));
        }
        if (state->single_pending && now_ms >= state->single_deadline_ms) {
            state->single_pending = false;
            emit(classifier, GESTURE_EVENT_SINGLE, side, state->pending_sequence, 0);
        }
    }
}
