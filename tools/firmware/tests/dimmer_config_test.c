#include <assert.h>
#include <stdint.h>

#include "dimmer_config.h"

static void test_defaults_match_approved_design(void)
{
    struct dimmer_config config = dimmer_config_defaults();

    assert(config.initial_on_delay_ms==0 && config.rise_transition_ms==0 && config.fall_transition_ms==0);
    assert(config.min_level==1 && config.max_level==254);
    assert(config.double_click_window_ms == 150);
    assert(config.long_press_ms == 250);
    assert(config.level_step_period_ms == 100);
    assert(config.level_step == 10);
    assert(config.short_press_mode == DIMMER_SHORT_SYMMETRIC_TOGGLE);
    assert(config.timer_duration_s == 600);
    assert(config.auto_off_mode == DIMMER_AUTO_OFF_DISABLED);
    assert(config.auto_off_duration_s == 600);
    assert(config.power_on_behavior == DIMMER_POWER_ON_LOCAL);
    assert(config.power_on_fallback == DIMMER_POWER_FALLBACK_PREVIOUS);
    assert(config.power_on_level == 254);
    assert(config.zigbee_restore_timeout_s == 10);
    assert(config.output_mode == DIMMER_OUTPUT_DIMMABLE);
    assert(config.reporting_mode == DIMMER_REPORT_OPTIMISTIC);
    assert(config.fixed_level == 254);
    assert(config.led_off.r == 0 && config.led_off.g == 0);
    assert(config.led_off.b == 255 && config.led_off.intensity == 10);
    assert(config.led_on.r == 0 && config.led_on.g == 255);
    assert(config.led_on.b == 0 && config.led_on.intensity == 10);
    assert(config.led_on_intensity_mode == DIMMER_LED_INTENSITY_FIXED);
    assert(config.led_on_min_intensity == 0);
    assert(config.led_on_max_intensity == 100);
    assert(dimmer_config_validate(&config));
}

static void test_vimar_defaults_preserve_generic_profile(void)
{
    struct dimmer_config config=dimmer_config_vimar_defaults();
    assert(config.long_press_ms==300);
    assert(config.level_step_period_ms==50);
    assert(config.level_step==3);
    assert(config.double_click_window_ms==150);
    assert(config.output_mode==DIMMER_OUTPUT_DIMMABLE);
    assert(config.power_on_fallback==DIMMER_POWER_FALLBACK_PREVIOUS);
    assert(config.led_on.r==255 && config.led_on.g==254 && config.led_on.b==250);
    assert(config.led_on.intensity==10);
    assert(config.led_off.r==255 && config.led_off.g==110 && config.led_off.b==84);
    assert(config.led_off.intensity==25);
    assert(config.led_on_intensity_mode==DIMMER_LED_INTENSITY_FOLLOW_LEVEL);
    assert(config.led_on_min_intensity==10 && config.led_on_max_intensity==100);
    assert(dimmer_config_validate(&config));
    config=dimmer_config_defaults();
    assert(config.long_press_ms==250);
    assert(config.level_step_period_ms==100);
    assert(config.level_step==10);
}

static void test_numeric_boundaries(void)
{
    struct dimmer_config config = dimmer_config_defaults();

#define ACCEPTS(field, minimum, maximum) do { \
    config = dimmer_config_defaults(); \
    config.field = (minimum); \
    assert(dimmer_config_validate(&config)); \
    config.field = (maximum); \
    assert(dimmer_config_validate(&config)); \
} while (0)

#define REJECTS(field, below, above) do { \
    config = dimmer_config_defaults(); \
    config.field = (below); \
    assert(!dimmer_config_validate(&config)); \
    config.field = (above); \
    assert(!dimmer_config_validate(&config)); \
} while (0)

    ACCEPTS(initial_on_delay_ms, 0, 60000);
    REJECTS(initial_on_delay_ms, 60001, UINT32_MAX);
    ACCEPTS(rise_transition_ms, 0, 60000);
    REJECTS(rise_transition_ms, 60001, UINT32_MAX);
    ACCEPTS(fall_transition_ms, 0, 60000);
    REJECTS(fall_transition_ms, 60001, UINT32_MAX);
    ACCEPTS(min_level, 1, 254);
    REJECTS(min_level, 0, 255);
    ACCEPTS(max_level, 1, 254);
    REJECTS(max_level, 0, 255);
    ACCEPTS(double_click_window_ms, 50, 600);
    REJECTS(double_click_window_ms, 49, 601);
    ACCEPTS(long_press_ms, 150, 2000);
    REJECTS(long_press_ms, 149, 2001);
    ACCEPTS(level_step_period_ms, 50, 500);
    REJECTS(level_step_period_ms, 49, 501);
    ACCEPTS(level_step, 1, 50);
    REJECTS(level_step, 0, 51);
    ACCEPTS(timer_duration_s, 1, 86400);
    REJECTS(timer_duration_s, 0, 86401);
    ACCEPTS(auto_off_duration_s, 1, 86400);
    REJECTS(auto_off_duration_s, 0, 86401);
    ACCEPTS(power_on_level, 1, 254);
    REJECTS(power_on_level, 0, 255);
    ACCEPTS(zigbee_restore_timeout_s, 1, 300);
    REJECTS(zigbee_restore_timeout_s, 0, 301);
    ACCEPTS(fixed_level, 1, 254);
    REJECTS(fixed_level, 0, 255);
    ACCEPTS(led_on.intensity, 0, 100);
    REJECTS(led_on.intensity, 101, 255);
    ACCEPTS(led_off.intensity, 0, 100);
    REJECTS(led_off.intensity, 101, 255);
    ACCEPTS(led_on_min_intensity, 0, 100);
    REJECTS(led_on_min_intensity, 101, 255);
    ACCEPTS(led_on_max_intensity, 0, 100);
    REJECTS(led_on_max_intensity, 101, 255);

#undef ACCEPTS
#undef REJECTS
}

static void test_enum_and_cross_field_validation(void)
{
    struct dimmer_config config = dimmer_config_defaults();

    config.min_level=200;config.max_level=100;assert(!dimmer_config_validate(&config));
    config=dimmer_config_defaults();
    config.output_mode = DIMMER_OUTPUT_STOCK_SWITCH;
    assert(dimmer_config_validate(&config));
    config.output_mode = (enum dimmer_output_mode)99;
    assert(!dimmer_config_validate(&config));

    config = dimmer_config_defaults();
    config.single_up_action = (enum dimmer_action)99;
    assert(!dimmer_config_validate(&config));

    config = dimmer_config_defaults();
    config.auto_off_mode = DIMMER_AUTO_OFF_MODE_COUNT;
    assert(!dimmer_config_validate(&config));

    config = dimmer_config_defaults();
    config.led_on_min_intensity = 80;
    config.led_on_max_intensity = 20;
    assert(!dimmer_config_validate(&config));
}

int main(void)
{
    test_defaults_match_approved_design();
    test_vimar_defaults_preserve_generic_profile();
    test_numeric_boundaries();
    test_enum_and_cross_field_validation();
    return 0;
}
