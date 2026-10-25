#ifndef VIMAR_ZIGBEE_REPORT_POLICY_H
#define VIMAR_ZIGBEE_REPORT_POLICY_H

#include <stdbool.h>
#include <stdint.h>

enum zigbee_report_action_kind {
    ZIGBEE_REPORT_NONE,
    ZIGBEE_REPORT_SEND_NOW,
    ZIGBEE_REPORT_SEND_AFTER,
};

struct zigbee_report_action {
    enum zigbee_report_action_kind kind;
    uint32_t delay_ms;
};

struct zigbee_report_policy {
    uint8_t retry_index;
    bool in_flight;
    bool dirty;
};

void zigbee_report_policy_init(struct zigbee_report_policy *policy);
struct zigbee_report_action zigbee_report_policy_request(
    struct zigbee_report_policy *policy);
struct zigbee_report_action zigbee_report_policy_complete(
    struct zigbee_report_policy *policy, bool success);

#endif
