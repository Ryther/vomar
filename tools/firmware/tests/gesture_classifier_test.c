#include <assert.h>
#include <stddef.h>

#include "gesture_classifier.h"
#include "local_action_mapper.h"

static struct gesture_event events[32];
static size_t event_count;

static void collect(const struct gesture_event *event, void *context)
{
    (void)context;
    events[event_count++] = *event;
}

static void reset(struct gesture_classifier *classifier,
                  const struct dimmer_config *config)
{
    event_count = 0;
    gesture_classifier_init(classifier, config, collect, NULL);
}

static void test_press_is_immediate_and_single_waits_for_window(void)
{
    struct gesture_classifier classifier;
    struct dimmer_config config = dimmer_config_defaults();
    reset(&classifier, &config);

    gesture_classifier_edge(&classifier, GESTURE_SIDE_UP, true, 100);
    assert(event_count == 1 && events[0].type == GESTURE_EVENT_PRESS);
    gesture_classifier_edge(&classifier, GESTURE_SIDE_UP, false, 120);
    gesture_classifier_tick(&classifier, 269);
    assert(event_count == 1);
    gesture_classifier_tick(&classifier, 270);
    assert(event_count == 2 && events[1].type == GESTURE_EVENT_SINGLE);
    assert(events[1].side == GESTURE_SIDE_UP);
}

static void test_same_side_double_and_mixed_side_singles(void)
{
    struct gesture_classifier classifier;
    struct dimmer_config config = dimmer_config_defaults();
    reset(&classifier, &config);

    gesture_classifier_edge(&classifier, GESTURE_SIDE_DOWN, true, 0);
    gesture_classifier_edge(&classifier, GESTURE_SIDE_DOWN, false, 20);
    gesture_classifier_edge(&classifier, GESTURE_SIDE_DOWN, true, 100);
    gesture_classifier_edge(&classifier, GESTURE_SIDE_DOWN, false, 120);
    assert(events[event_count - 1].type == GESTURE_EVENT_DOUBLE);
    assert(events[event_count - 1].side == GESTURE_SIDE_DOWN);

    reset(&classifier, &config);
    gesture_classifier_edge(&classifier, GESTURE_SIDE_UP, true, 0);
    gesture_classifier_edge(&classifier, GESTURE_SIDE_UP, false, 10);
    gesture_classifier_edge(&classifier, GESTURE_SIDE_DOWN, true, 50);
    gesture_classifier_edge(&classifier, GESTURE_SIDE_DOWN, false, 60);
    gesture_classifier_tick(&classifier, 210);
    assert(event_count == 4);
    assert(events[2].type == GESTURE_EVENT_SINGLE);
    assert(events[3].type == GESTURE_EVENT_SINGLE);
}

static void test_long_emits_once_and_release_carries_duration(void)
{
    struct gesture_classifier classifier;
    struct dimmer_config config = dimmer_config_defaults();
    reset(&classifier, &config);

    gesture_classifier_edge(&classifier, GESTURE_SIDE_UP, true, 1000);
    gesture_classifier_tick(&classifier, 1249);
    assert(event_count == 1);
    gesture_classifier_tick(&classifier, 1250);
    assert(event_count == 2 && events[1].type == GESTURE_EVENT_LONG);
    uint32_t sequence = events[1].sequence_id;
    gesture_classifier_tick(&classifier, 1600);
    assert(event_count == 2);
    gesture_classifier_edge(&classifier, GESTURE_SIDE_UP, false, 1750);
    assert(event_count == 3 && events[2].type == GESTURE_EVENT_RELEASE);
    assert(events[2].held_ms == 750);
    assert(events[2].sequence_id == sequence);
}

static void test_action_mapping_profiles(void)
{
    struct dimmer_config config = dimmer_config_defaults();
    assert(local_action_for(&config, GESTURE_EVENT_SINGLE, GESTURE_SIDE_UP) ==
        DIMMER_ACTION_TOGGLE);
    assert(local_action_for(&config, GESTURE_EVENT_DOUBLE, GESTURE_SIDE_UP) ==
        DIMMER_ACTION_EVENT_ONLY);

    config.short_press_mode = DIMMER_SHORT_DIRECTIONAL;
    assert(local_action_for(&config, GESTURE_EVENT_SINGLE, GESTURE_SIDE_UP) ==
        DIMMER_ACTION_ON);
    assert(local_action_for(&config, GESTURE_EVENT_SINGLE, GESTURE_SIDE_DOWN) ==
        DIMMER_ACTION_OFF);

    config.short_press_mode = DIMMER_SHORT_CUSTOM;
    config.single_up_action = DIMMER_ACTION_TIMED_ON;
    config.double_down_action = DIMMER_ACTION_DISABLED;
    assert(local_action_for(&config, GESTURE_EVENT_SINGLE, GESTURE_SIDE_UP) ==
        DIMMER_ACTION_TIMED_ON);
    assert(local_action_for(&config, GESTURE_EVENT_DOUBLE, GESTURE_SIDE_DOWN) ==
        DIMMER_ACTION_DISABLED);
    assert(local_action_for(&config, GESTURE_EVENT_LONG, GESTURE_SIDE_UP) ==
        DIMMER_ACTION_EVENT_ONLY);
    assert(local_action_level_delta(&config, GESTURE_SIDE_UP) == 10);
    assert(local_action_level_delta(&config, GESTURE_SIDE_DOWN) == -10);
}

int main(void)
{
    test_press_is_immediate_and_single_waits_for_window();
    test_same_side_double_and_mixed_side_singles();
    test_long_emits_once_and_release_carries_duration();
    test_action_mapping_profiles();
    return 0;
}
