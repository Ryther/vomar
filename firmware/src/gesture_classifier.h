#ifndef VIMAR_GESTURE_CLASSIFIER_H
#define VIMAR_GESTURE_CLASSIFIER_H

#include <stdbool.h>
#include <stdint.h>
#include "dimmer_config.h"

enum gesture_side { GESTURE_SIDE_UP, GESTURE_SIDE_DOWN, GESTURE_SIDE_COUNT };
enum gesture_event_type { GESTURE_EVENT_PRESS, GESTURE_EVENT_SINGLE,
    GESTURE_EVENT_DOUBLE, GESTURE_EVENT_LONG, GESTURE_EVENT_RELEASE };

struct gesture_event {
    enum gesture_event_type type;
    enum gesture_side side;
    uint32_t sequence_id;
    uint32_t held_ms;
};

typedef void (*gesture_event_callback)(const struct gesture_event *, void *);

struct gesture_side_state {
    bool pressed;
    bool long_emitted;
    bool second_press;
    bool single_pending;
    uint64_t pressed_at_ms;
    uint64_t single_deadline_ms;
    uint32_t active_sequence;
    uint32_t pending_sequence;
};

struct gesture_classifier {
    struct dimmer_config config;
    struct gesture_side_state sides[GESTURE_SIDE_COUNT];
    uint32_t next_sequence;
    gesture_event_callback callback;
    void *callback_context;
};

void gesture_classifier_init(struct gesture_classifier *,
    const struct dimmer_config *, gesture_event_callback, void *);
void gesture_classifier_edge(struct gesture_classifier *, enum gesture_side,
    bool pressed, uint64_t now_ms);
void gesture_classifier_tick(struct gesture_classifier *, uint64_t now_ms);

#endif
