#ifndef VIMAR_DIMMER_CONFIG_H
#define VIMAR_DIMMER_CONFIG_H

#include <stdbool.h>
#include <stdint.h>

enum dimmer_short_press_mode {
    DIMMER_SHORT_DIRECTIONAL,
    DIMMER_SHORT_SYMMETRIC_TOGGLE,
    DIMMER_SHORT_CUSTOM,
    DIMMER_SHORT_MODE_COUNT,
};

enum dimmer_action {
    DIMMER_ACTION_TOGGLE,
    DIMMER_ACTION_ON,
    DIMMER_ACTION_OFF,
    DIMMER_ACTION_TIMED_ON,
    DIMMER_ACTION_EVENT_ONLY,
    DIMMER_ACTION_DISABLED,
    DIMMER_ACTION_BYPASS_ON,
    /* Append-only: values 0..6 are persisted and used by legacy MQTT. */
    DIMMER_ACTION_TIMED_ON_1, DIMMER_ACTION_TIMED_ON_2,
    DIMMER_ACTION_TIMED_ON_3, DIMMER_ACTION_TIMED_ON_4,
    DIMMER_ACTION_TIMED_TOGGLE_1, DIMMER_ACTION_TIMED_TOGGLE_2,
    DIMMER_ACTION_TIMED_TOGGLE_3, DIMMER_ACTION_TIMED_TOGGLE_4,
    DIMMER_ACTION_COUNT,
};

enum dimmer_auto_off_mode {
    DIMMER_AUTO_OFF_DISABLED,
    DIMMER_AUTO_OFF_EVERY_ON,
    DIMMER_AUTO_OFF_PHYSICAL_ON_ONLY,
    DIMMER_AUTO_OFF_MODE_COUNT,
};

enum dimmer_power_on_behavior {
    DIMMER_POWER_ON_LOCAL,
    DIMMER_POWER_ON_AWAIT_ZIGBEE,
    DIMMER_POWER_ON_BEHAVIOR_COUNT,
};

enum dimmer_power_on_fallback {
    DIMMER_POWER_FALLBACK_OFF,
    DIMMER_POWER_FALLBACK_ON,
    DIMMER_POWER_FALLBACK_PREVIOUS,
    DIMMER_POWER_FALLBACK_COUNT,
};

enum dimmer_output_mode {
    DIMMER_OUTPUT_DIMMABLE,
    DIMMER_OUTPUT_FIXED_LEVEL,
    DIMMER_OUTPUT_STOCK_SWITCH,
    DIMMER_OUTPUT_MODE_COUNT,
};

enum dimmer_reporting_mode {
    DIMMER_REPORT_OPTIMISTIC,
    DIMMER_REPORT_ACKNOWLEDGED,
    DIMMER_REPORT_PHYSICAL,
    DIMMER_REPORT_MODE_COUNT,
};

enum dimmer_led_intensity_mode {
    DIMMER_LED_INTENSITY_FIXED,
    DIMMER_LED_INTENSITY_FOLLOW_LEVEL,
    DIMMER_LED_INTENSITY_INVERSE_LEVEL,
    DIMMER_LED_INTENSITY_MODE_COUNT,
};

enum dimmer_phase_cut_mode {
    DIMMER_PHASE_TRAILING_EDGE = 0,
    DIMMER_PHASE_LEADING_EDGE = 1,
    DIMMER_PHASE_MODE_COUNT,
};

struct dimmer_led_profile {
    uint8_t r;
    uint8_t g;
    uint8_t b;
    uint8_t intensity;
};

struct dimmer_config {
    uint32_t initial_on_delay_ms;
    uint32_t rise_transition_ms;
    uint32_t fall_transition_ms;
    uint8_t min_level;
    uint8_t max_level;
    uint16_t double_click_window_ms;
    uint16_t long_press_ms;
    uint16_t level_step_period_ms;
    uint8_t level_step;
    enum dimmer_short_press_mode short_press_mode;
    enum dimmer_action single_up_action;
    enum dimmer_action single_down_action;
    enum dimmer_action double_up_action;
    enum dimmer_action double_down_action;
    uint32_t timer_duration_s; /* Template 1; legacy timed_on uses this too. */
    uint32_t timer_2_duration_s, timer_3_duration_s, timer_4_duration_s;
    uint8_t ramp_start_level, ramp_end_level;
    enum dimmer_auto_off_mode auto_off_mode;
    uint32_t auto_off_duration_s;
    enum dimmer_power_on_behavior power_on_behavior;
    enum dimmer_power_on_fallback power_on_fallback;
    uint8_t power_on_level;
    uint16_t zigbee_restore_timeout_s;
    enum dimmer_output_mode output_mode;
    enum dimmer_reporting_mode reporting_mode;
    uint8_t fixed_level;
    struct dimmer_led_profile led_on;
    struct dimmer_led_profile led_off;
    enum dimmer_led_intensity_mode led_on_intensity_mode;
    uint8_t led_on_min_intensity;
    uint8_t led_on_max_intensity;
    enum dimmer_phase_cut_mode phase_cut_mode;
};

struct dimmer_config dimmer_config_defaults(void);
struct dimmer_config dimmer_config_vimar_defaults(void);
bool dimmer_config_validate(const struct dimmer_config *config);

#endif
