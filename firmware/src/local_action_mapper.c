#include "local_action_mapper.h"

enum dimmer_action local_action_for(const struct dimmer_config *config,
    enum gesture_event_type type, enum gesture_side side)
{
    if (type != GESTURE_EVENT_SINGLE && type != GESTURE_EVENT_DOUBLE) {
        return DIMMER_ACTION_EVENT_ONLY;
    }
    if (type == GESTURE_EVENT_SINGLE && config->short_press_mode == DIMMER_SHORT_DIRECTIONAL) {
        return side == GESTURE_SIDE_UP ? DIMMER_ACTION_ON : DIMMER_ACTION_OFF;
    }
    if (type == GESTURE_EVENT_SINGLE && config->short_press_mode == DIMMER_SHORT_SYMMETRIC_TOGGLE) {
        return DIMMER_ACTION_TOGGLE;
    }
    if (type == GESTURE_EVENT_SINGLE) {
        return side == GESTURE_SIDE_UP ? config->single_up_action : config->single_down_action;
    }
    return side == GESTURE_SIDE_UP ? config->double_up_action : config->double_down_action;
}

int16_t local_action_level_delta(const struct dimmer_config *config,
    enum gesture_side side)
{
    return side == GESTURE_SIDE_UP ? config->level_step : -(int16_t)config->level_step;
}
