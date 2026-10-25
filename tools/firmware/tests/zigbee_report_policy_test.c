#include <assert.h>
#include <stdbool.h>
#include <stdint.h>

#include "zigbee_report_policy.h"

static void test_first_request_sends_immediately(void)
{
    struct zigbee_report_policy policy;
    zigbee_report_policy_init(&policy);

    struct zigbee_report_action action = zigbee_report_policy_request(&policy);

    assert(action.kind == ZIGBEE_REPORT_SEND_NOW);
    assert(action.delay_ms == 0);
}

static void test_failure_uses_three_bounded_retries(void)
{
    struct zigbee_report_policy policy;
    zigbee_report_policy_init(&policy);
    (void)zigbee_report_policy_request(&policy);

    const uint32_t expected_delays[] = {1000, 3000, 10000};
    for (unsigned int index = 0; index < 3; ++index) {
        struct zigbee_report_action action =
            zigbee_report_policy_complete(&policy, false);
        assert(action.kind == ZIGBEE_REPORT_SEND_AFTER);
        assert(action.delay_ms == expected_delays[index]);
    }

    struct zigbee_report_action exhausted =
        zigbee_report_policy_complete(&policy, false);
    assert(exhausted.kind == ZIGBEE_REPORT_NONE);
}

static void test_change_during_send_is_coalesced_into_fresh_snapshot(void)
{
    struct zigbee_report_policy policy;
    zigbee_report_policy_init(&policy);
    (void)zigbee_report_policy_request(&policy);

    struct zigbee_report_action queued = zigbee_report_policy_request(&policy);
    assert(queued.kind == ZIGBEE_REPORT_NONE);

    struct zigbee_report_action completed =
        zigbee_report_policy_complete(&policy, true);
    assert(completed.kind == ZIGBEE_REPORT_SEND_NOW);

    struct zigbee_report_action final =
        zigbee_report_policy_complete(&policy, true);
    assert(final.kind == ZIGBEE_REPORT_NONE);
}

static void test_success_resets_retry_sequence(void)
{
    struct zigbee_report_policy policy;
    zigbee_report_policy_init(&policy);
    (void)zigbee_report_policy_request(&policy);
    (void)zigbee_report_policy_complete(&policy, false);
    (void)zigbee_report_policy_complete(&policy, true);

    (void)zigbee_report_policy_request(&policy);
    struct zigbee_report_action retry =
        zigbee_report_policy_complete(&policy, false);
    assert(retry.kind == ZIGBEE_REPORT_SEND_AFTER);
    assert(retry.delay_ms == 1000);
}

int main(void)
{
    test_first_request_sends_immediately();
    test_failure_uses_three_bounded_retries();
    test_change_during_send_is_coalesced_into_fresh_snapshot();
    test_success_resets_retry_sequence();
    return 0;
}
