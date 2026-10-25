#ifndef VIMAR_LOCAL_ACTION_MAPPER_H
#define VIMAR_LOCAL_ACTION_MAPPER_H

#include <stdint.h>
#include "dimmer_config.h"
#include "gesture_classifier.h"

enum dimmer_action local_action_for(const struct dimmer_config *,
    enum gesture_event_type, enum gesture_side);
int16_t local_action_level_delta(const struct dimmer_config *, enum gesture_side);

#endif
