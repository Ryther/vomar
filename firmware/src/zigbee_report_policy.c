#include "zigbee_report_policy.h"

#include <stddef.h>

static const uint32_t retry_delays_ms[] = {1000, 3000, 10000};

static struct zigbee_report_action action(
    enum zigbee_report_action_kind kind, uint32_t delay_ms)
{
    return (struct zigbee_report_action){.kind = kind, .delay_ms = delay_ms};
}

void zigbee_report_policy_init(struct zigbee_report_policy *policy)
{
    *policy = (struct zigbee_report_policy){0};
}

struct zigbee_report_action zigbee_report_policy_request(
    struct zigbee_report_policy *policy)
{
    if (policy->in_flight) {
        policy->dirty = true;
        return action(ZIGBEE_REPORT_NONE, 0);
    }

    policy->in_flight = true;
    policy->retry_index = 0;
    return action(ZIGBEE_REPORT_SEND_NOW, 0);
}

struct zigbee_report_action zigbee_report_policy_complete(
    struct zigbee_report_policy *policy, bool success)
{
    if (!success && policy->retry_index <
            sizeof(retry_delays_ms) / sizeof(retry_delays_ms[0])) {
        uint32_t delay_ms = retry_delays_ms[policy->retry_index++];
        return action(ZIGBEE_REPORT_SEND_AFTER, delay_ms);
    }

    policy->retry_index = 0;
    if (policy->dirty) {
        policy->dirty = false;
        return action(ZIGBEE_REPORT_SEND_NOW, 0);
    }

    policy->in_flight = false;
    return action(ZIGBEE_REPORT_NONE, 0);
}
