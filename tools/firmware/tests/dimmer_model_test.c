#include <assert.h>
#include <stdbool.h>
#include <stdint.h>

#include "dimmer_model.h"

static struct dimmer_secondary_capabilities full_capabilities(void)
{
    return (struct dimmer_secondary_capabilities) {
        .acceptance_feedback = true,
        .physical_feedback = true,
        .stock_switch_mode = false,
    };
}

static void test_target_changes_before_effective_feedback(void)
{
    struct dimmer_model model;
    struct dimmer_config config = dimmer_config_defaults();
    dimmer_model_init(&model, &config, false, 100);

    uint32_t operation = dimmer_model_request(&model, true, 180, 1000);
    const struct dimmer_state *state = dimmer_model_state(&model);
    assert(operation != 0);
    assert(state->target_on && state->target_level == 180);
    assert(!state->on && state->level == 100);

    assert(dimmer_model_apply_effective(&model, operation, true, 180));
    assert(dimmer_model_state(&model)->on);
    assert(dimmer_model_state(&model)->level == 180);
}

static void test_stale_feedback_is_ignored(void)
{
    struct dimmer_model model;
    struct dimmer_config config = dimmer_config_defaults();
    dimmer_model_init(&model, &config, false, 100);

    uint32_t first = dimmer_model_request(&model, true, 120, 1000);
    uint32_t second = dimmer_model_request(&model, true, 200, 1100);
    assert(second != first);
    assert(!dimmer_model_apply_effective(&model, first, true, 120));
    assert(!dimmer_model_state(&model)->on);
    assert(dimmer_model_apply_effective(&model, second, true, 200));
    assert(dimmer_model_state(&model)->level == 200);
}

static void test_timer_expiry_requests_off_without_fabricating_feedback(void)
{
    struct dimmer_model model;
    struct dimmer_config config = dimmer_config_defaults();
    dimmer_model_init(&model, &config, true, 100);

    dimmer_model_start_off_timer(&model, 1000, 30000);
    assert(!dimmer_model_tick(&model, 30999));
    assert(dimmer_model_tick(&model, 31000));
    assert(!dimmer_model_state(&model)->target_on);
    assert(dimmer_model_state(&model)->on);
    assert(!dimmer_model_state(&model)->off_timer_active);
}

static void test_restore_wait_and_physical_priority(void)
{
    struct dimmer_model model;
    struct dimmer_config config = dimmer_config_defaults();
    config.power_on_behavior = DIMMER_POWER_ON_AWAIT_ZIGBEE;
    config.power_on_fallback = DIMMER_POWER_FALLBACK_ON;
    config.zigbee_restore_timeout_s = 10;
    dimmer_model_init_at(&model, &config, true, 90, 1000);
    assert(dimmer_model_state(&model)->restore_waiting);
    assert(!dimmer_model_state(&model)->on);

    assert(!dimmer_model_tick(&model, 10999));
    assert(dimmer_model_tick(&model, 11000));
    assert(dimmer_model_state(&model)->target_on);

    dimmer_model_init_at(&model, &config, false, 90, 2000);
    dimmer_model_cancel_restore(&model);
    assert(!dimmer_model_state(&model)->restore_waiting);
    (void)dimmer_model_request(&model, true, 140, 2100);
    assert(dimmer_model_state(&model)->target_level == 140);
    assert(!dimmer_model_tick(&model, 12000));
}

static void test_mode_capability_validation(void)
{
    struct dimmer_config config = dimmer_config_defaults();
    struct dimmer_secondary_capabilities caps = full_capabilities();

    assert(dimmer_model_modes_supported(&config, &caps));
    config.reporting_mode = DIMMER_REPORT_ACKNOWLEDGED;
    caps.acceptance_feedback = false;
    assert(!dimmer_model_modes_supported(&config, &caps));
    config.reporting_mode = DIMMER_REPORT_PHYSICAL;
    caps.physical_feedback = false;
    assert(!dimmer_model_modes_supported(&config, &caps));
    config.reporting_mode = DIMMER_REPORT_OPTIMISTIC;
    config.output_mode = DIMMER_OUTPUT_STOCK_SWITCH;
    assert(!dimmer_model_modes_supported(&config, &caps));
}

static void test_fixed_level_and_faults(void)
{
    struct dimmer_model model;
    struct dimmer_config config = dimmer_config_defaults();
    config.output_mode = DIMMER_OUTPUT_FIXED_LEVEL;
    config.fixed_level = 77;
    dimmer_model_init(&model, &config, false, 10);
    uint32_t operation = dimmer_model_request(&model, true, 200, 1000);
    assert(dimmer_model_state(&model)->target_level == 77);

    dimmer_model_fail(&model, operation, DIMMER_FAULT_SECONDARY_TIMEOUT);
    assert(dimmer_model_state(&model)->fault.code == DIMMER_FAULT_SECONDARY_TIMEOUT);
    assert(dimmer_model_state(&model)->fault.active);
    assert(dimmer_model_state(&model)->fault.occurrences == 1);
    dimmer_model_clear_fault(&model, DIMMER_FAULT_SECONDARY_TIMEOUT);
    assert(!dimmer_model_state(&model)->fault.active);
}

static void test_symmetric_toggle_retains_level(void)
{
    struct dimmer_model model;
    struct dimmer_config config = dimmer_config_defaults();
    config.short_press_mode = DIMMER_SHORT_SYMMETRIC_TOGGLE;
    dimmer_model_init(&model, &config, false, 127);

    dimmer_model_input(&model, DIMMER_INPUT_SHORT_UP, 100);
    assert(dimmer_model_state(&model)->on);
    assert(dimmer_model_state(&model)->level == 127);

    dimmer_model_input(&model, DIMMER_INPUT_SHORT_DOWN, 200);
    assert(!dimmer_model_state(&model)->on);
    assert(dimmer_model_state(&model)->level == 127);
}

static void test_release_records_hold_duration(void)
{
    struct dimmer_model model;
    struct dimmer_config config = dimmer_config_defaults();
    dimmer_model_init(&model, &config, true, 100);

    dimmer_model_input(&model, DIMMER_INPUT_LONG_UP, 1000);
    dimmer_model_input(&model, DIMMER_INPUT_RELEASE_UP, 1750);

    assert(dimmer_model_state(&model)->last_event == DIMMER_EVENT_RELEASE_UP);
    assert(dimmer_model_state(&model)->last_hold_ms == 750);
}

static void test_off_cancels_running_timer(void)
{
    struct dimmer_model model;
    struct dimmer_config config = dimmer_config_defaults();
    dimmer_model_init(&model, &config, true, 100);

    dimmer_model_start_off_timer(&model, 1000, 30000);
    assert(dimmer_model_state(&model)->off_timer_active);
    dimmer_model_input(&model, DIMMER_INPUT_SHORT_DOWN, 2000);
    assert(!dimmer_model_state(&model)->on);
    assert(!dimmer_model_state(&model)->off_timer_active);
}

static void test_bypass_lasts_until_effective_off(void)
{
    struct dimmer_model model;
    struct dimmer_config config = dimmer_config_defaults();
    dimmer_model_init(&model, &config, false, 100);

    dimmer_model_start_off_timer(&model, 1000, 30000);
    assert(dimmer_model_timer_remaining_s(&model, 1001) == 30);
    assert(dimmer_model_timer_remaining_s(&model, 2000) == 29);
    dimmer_model_bypass_off_timer(&model);
    assert(dimmer_model_state(&model)->auto_off_bypassed);
    assert(!dimmer_model_state(&model)->off_timer_active);
    assert(dimmer_model_timer_remaining_s(&model, 2000) == 0);

    uint32_t operation = dimmer_model_request(&model, false, 100, 3000);
    assert(!dimmer_model_state(&model)->auto_off_bypassed);
    assert(dimmer_model_apply_effective(&model, operation, false, 100));
    assert(!dimmer_model_state(&model)->auto_off_bypassed);
}

static void test_dimmable_bounds_preserve_off_and_fixed_output(void)
{
    struct dimmer_config cfg=dimmer_config_defaults();struct dimmer_model m;
    cfg.min_level=20;cfg.max_level=180;
    dimmer_model_init(&m,&cfg,true,254);assert(m.state.level==180);
    uint32_t op=dimmer_model_request(&m,true,1,0);assert(m.state.target_level==20);
    assert(dimmer_model_apply_effective(&m,op,true,20));
    dimmer_model_request(&m,false,0,1);assert(!m.state.target_on && m.state.target_level==20);
    cfg.output_mode=DIMMER_OUTPUT_FIXED_LEVEL;cfg.fixed_level=250;
    dimmer_model_init(&m,&cfg,true,250);assert(m.state.level==250);
    dimmer_model_request(&m,true,1,0);assert(m.state.target_level==250);
}

int main(void)
{
    test_dimmable_bounds_preserve_off_and_fixed_output();
    test_target_changes_before_effective_feedback();
    test_stale_feedback_is_ignored();
    test_timer_expiry_requests_off_without_fabricating_feedback();
    test_restore_wait_and_physical_priority();
    test_mode_capability_validation();
    test_fixed_level_and_faults();
    test_symmetric_toggle_retains_level();
    test_release_records_hold_duration();
    test_off_cancels_running_timer();
    test_bypass_lasts_until_effective_off();
    struct dimmer_config cfg=dimmer_config_defaults();
    struct dimmer_secondary_capabilities caps={false,false,false};
    cfg.output_mode=DIMMER_OUTPUT_STOCK_SWITCH;cfg.reporting_mode=DIMMER_REPORT_PHYSICAL;
    assert(dimmer_model_sanitize_modes(&cfg,&caps));
    assert(cfg.output_mode==DIMMER_OUTPUT_DIMMABLE&&cfg.reporting_mode==DIMMER_REPORT_OPTIMISTIC);
    assert(dimmer_model_modes_supported(&cfg,&caps));
    assert(!dimmer_model_sanitize_modes(&cfg,&caps));
    return 0;
}
