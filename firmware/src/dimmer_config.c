#include "dimmer_config.h"

#include <stddef.h>

struct dimmer_config dimmer_config_defaults(void)
{
    return (struct dimmer_config) {
#if defined(CONFIG_RESEARCH_STOCK_CONFIG19)
        .phase_cut_mode = CONFIG_RESEARCH_STOCK_CONFIG19,
#else
        .phase_cut_mode = DIMMER_PHASE_TRAILING_EDGE,
#endif
        .initial_on_delay_ms = 0,
        .rise_transition_ms = 0,
        .fall_transition_ms = 0,
        .min_level = 1,
        .max_level = 254,
        .double_click_window_ms = 150,
        .long_press_ms = 250,
        .level_step_period_ms = 100,
        .level_step = 10,
        .short_press_mode = DIMMER_SHORT_SYMMETRIC_TOGGLE,
        .single_up_action = DIMMER_ACTION_TOGGLE,
        .single_down_action = DIMMER_ACTION_TOGGLE,
        .double_up_action = DIMMER_ACTION_EVENT_ONLY,
        .double_down_action = DIMMER_ACTION_EVENT_ONLY,
        .timer_duration_s = 600,
        .timer_2_duration_s = 600, .timer_3_duration_s = 600, .timer_4_duration_s = 600,
        .ramp_start_level = 0, .ramp_end_level = 0,
        .auto_off_mode = DIMMER_AUTO_OFF_DISABLED,
        .auto_off_duration_s = 600,
        .power_on_behavior = DIMMER_POWER_ON_LOCAL,
        .power_on_fallback = DIMMER_POWER_FALLBACK_PREVIOUS,
        .power_on_level = 254,
        .zigbee_restore_timeout_s = 10,
        .output_mode = DIMMER_OUTPUT_DIMMABLE,
        .reporting_mode = DIMMER_REPORT_OPTIMISTIC,
        .fixed_level = 254,
        .led_on = { .r = 0, .g = 255, .b = 0, .intensity = 10 },
        .led_off = { .r = 0, .g = 0, .b = 255, .intensity = 10 },
        .led_on_intensity_mode = DIMMER_LED_INTENSITY_FIXED,
        .led_on_min_intensity = 0,
        .led_on_max_intensity = 100,
    };
}

struct dimmer_config dimmer_config_vimar_defaults(void)
{
    struct dimmer_config config = dimmer_config_defaults();
    config.long_press_ms = 300;
    config.level_step_period_ms = 50;
    config.level_step = 3;
    config.led_on = (struct dimmer_led_profile) { .r = 255, .g = 254, .b = 250, .intensity = 10 };
    config.led_off = (struct dimmer_led_profile) { .r = 255, .g = 110, .b = 84, .intensity = 25 };
    config.led_on_intensity_mode = DIMMER_LED_INTENSITY_FOLLOW_LEVEL;
    config.led_on_min_intensity = 10;
    return config;
}

static bool in_range_u32(uint32_t value, uint32_t minimum, uint32_t maximum)
{
    return value >= minimum && value <= maximum;
}

static bool action_valid(enum dimmer_action action)
{
    return action >= DIMMER_ACTION_TOGGLE && action < DIMMER_ACTION_COUNT;
}

bool dimmer_config_validate(const struct dimmer_config *config)
{
    if (config == NULL) {
        return false;
    }
    return config->phase_cut_mode >= DIMMER_PHASE_TRAILING_EDGE &&
        config->phase_cut_mode < DIMMER_PHASE_MODE_COUNT &&
        in_range_u32(config->initial_on_delay_ms, 0, 60000) &&
        in_range_u32(config->rise_transition_ms, 0, 60000) &&
        in_range_u32(config->fall_transition_ms, 0, 60000) &&
        in_range_u32(config->min_level, 1, 254) &&
        in_range_u32(config->max_level, 1, 254) &&
        config->min_level <= config->max_level &&
        in_range_u32(config->double_click_window_ms, 50, 600) &&
        in_range_u32(config->long_press_ms, 150, 2000) &&
        in_range_u32(config->level_step_period_ms, 50, 500) &&
        in_range_u32(config->level_step, 1, 50) &&
        config->short_press_mode >= DIMMER_SHORT_DIRECTIONAL &&
        config->short_press_mode < DIMMER_SHORT_MODE_COUNT &&
        action_valid(config->single_up_action) &&
        action_valid(config->single_down_action) &&
        action_valid(config->double_up_action) &&
        action_valid(config->double_down_action) &&
        in_range_u32(config->timer_duration_s, 1, 86400) &&
        in_range_u32(config->timer_2_duration_s, 1, 86400) &&
        in_range_u32(config->timer_3_duration_s, 1, 86400) &&
        in_range_u32(config->timer_4_duration_s, 1, 86400) &&
        config->ramp_start_level <= 254 && config->ramp_end_level <= 254 &&
        config->auto_off_mode >= DIMMER_AUTO_OFF_DISABLED &&
        config->auto_off_mode < DIMMER_AUTO_OFF_MODE_COUNT &&
        in_range_u32(config->auto_off_duration_s, 1, 86400) &&
        config->power_on_behavior >= DIMMER_POWER_ON_LOCAL &&
        config->power_on_behavior < DIMMER_POWER_ON_BEHAVIOR_COUNT &&
        config->power_on_fallback >= DIMMER_POWER_FALLBACK_OFF &&
        config->power_on_fallback < DIMMER_POWER_FALLBACK_COUNT &&
        in_range_u32(config->power_on_level, 1, 254) &&
        in_range_u32(config->zigbee_restore_timeout_s, 1, 300) &&
        config->output_mode >= DIMMER_OUTPUT_DIMMABLE &&
        config->output_mode < DIMMER_OUTPUT_MODE_COUNT &&
        config->reporting_mode >= DIMMER_REPORT_OPTIMISTIC &&
        config->reporting_mode < DIMMER_REPORT_MODE_COUNT &&
        in_range_u32(config->fixed_level, 1, 254) &&
        in_range_u32(config->led_on.intensity, 0, 100) &&
        in_range_u32(config->led_off.intensity, 0, 100) &&
        config->led_on_intensity_mode >= DIMMER_LED_INTENSITY_FIXED &&
        config->led_on_intensity_mode < DIMMER_LED_INTENSITY_MODE_COUNT &&
        in_range_u32(config->led_on_min_intensity, 0, 100) &&
        in_range_u32(config->led_on_max_intensity, 0, 100) &&
        config->led_on_min_intensity <= config->led_on_max_intensity;
}
