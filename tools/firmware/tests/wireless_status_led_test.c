#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include "wireless_status_led.h"

static void equal_output(struct led_output actual, struct led_output expected)
{
    assert(actual.r == expected.r && actual.g == expected.g && actual.b == expected.b);
    assert(actual.intensity == expected.intensity && actual.effect == expected.effect);
}

static void test_bluetooth_and_recovery_have_distinct_alternating_colours(void)
{
    const struct led_output base = {18, 42, 90, 7, LED_EFFECT_STATIC};
    const struct led_output blue = {0, 0, 255, 50, LED_EFFECT_STATIC};
    const struct led_output green = {0, 255, 0, 50, LED_EFFECT_STATIC};
    const struct led_output red = {255, 0, 0, 50, LED_EFFECT_STATIC};
    const uint64_t times[] = {0, 1, 499, 500, 501, 999, 1000, 1499, 1500};
    const bool second[] = {false, false, false, true, true, true, false, false, true};
    for (unsigned int i = 0; i < sizeof(times) / sizeof(times[0]); ++i) {
        equal_output(wireless_status_led_resolve(WIRELESS_STATUS_LED_BLUETOOTH, false, &base, times[i]), second[i] ? green : blue);
        equal_output(wireless_status_led_resolve(WIRELESS_STATUS_LED_RECOVERY, false, &base, times[i]), second[i] ? red : blue);
    }
    /* Every sampled instant remains one full colour; there is no blank phase. */
    for (uint64_t time = 0; time < 3000; time += 13) {
        struct led_output out = wireless_status_led_resolve(WIRELESS_STATUS_LED_RECOVERY, false, NULL, time);
        assert(out.r + out.g + out.b == 255 && out.intensity == 50 && out.effect == LED_EFFECT_STATIC);
    }
}

static void test_fault_keeps_the_existing_highest_priority_indication(void)
{
    struct dimmer_config config = dimmer_config_defaults();
    struct led_controller controller;
    const struct led_output white = {255, 255, 255, 90, LED_EFFECT_STATIC};
    led_controller_init(&controller, &config);
    led_controller_set_override(&controller, &white, 0, 0);
    const struct led_output base = led_controller_resolve(&controller, true, 254, 0);
    led_controller_set_fault(&controller, true);
    const struct led_output fault = led_controller_resolve(&controller, true, 254, 0);
    for (enum wireless_status_led_mode mode = WIRELESS_STATUS_LED_NORMAL; mode <= WIRELESS_STATUS_LED_RECOVERY; ++mode) {
        equal_output(wireless_status_led_resolve(mode, true, &base, 0), fault);
        equal_output(wireless_status_led_resolve(mode, true, NULL, 500), fault);
        equal_output(wireless_status_led_resolve(mode, true, &base, UINT64_MAX), fault);
    }
    assert(fault.r == 255 && fault.g == 0 && fault.b == 0 && fault.intensity == 100 && fault.effect == LED_EFFECT_SLOW_BLINK);
}

static void test_normal_profiles_and_level_scaling_pass_through(void)
{
    struct dimmer_config config = dimmer_config_defaults();
    config.led_on = (struct dimmer_led_profile){11, 22, 33, 44};
    config.led_off = (struct dimmer_led_profile){55, 66, 77, 88};
    config.led_on_intensity_mode = DIMMER_LED_INTENSITY_FOLLOW_LEVEL;
    config.led_on_min_intensity = 20;
    config.led_on_max_intensity = 80;
    struct led_controller controller;
    led_controller_init(&controller, &config);
    const uint8_t levels[] = {1, 100, 254};
    for (unsigned int on = 0; on < 2; ++on) {
        for (unsigned int i = 0; i < sizeof(levels); ++i) {
            const struct led_output base = led_controller_resolve(&controller, on, levels[i], 250);
            equal_output(wireless_status_led_resolve(WIRELESS_STATUS_LED_NORMAL, false, &base, 250), base);
            equal_output(wireless_status_led_resolve(WIRELESS_STATUS_LED_NORMAL, false, &base, UINT64_MAX), base);
        }
    }
}

static void test_wireless_overlay_does_not_consume_or_rewrite_override(void)
{
    struct dimmer_config config = dimmer_config_defaults();
    struct led_controller controller;
    const struct led_output override = {91, 92, 93, 37, LED_EFFECT_SLOW_BLINK};
    led_controller_init(&controller, &config);
    led_controller_set_override(&controller, &override, 100, 2000);
    struct led_output base = led_controller_resolve(&controller, false, 1, 200);
    (void)wireless_status_led_resolve(WIRELESS_STATUS_LED_BLUETOOTH, false, &base, 500);
    (void)wireless_status_led_resolve(WIRELESS_STATUS_LED_RECOVERY, false, &base, 1000);
    equal_output(base, override);
    equal_output(wireless_status_led_resolve(WIRELESS_STATUS_LED_NORMAL, false, &base, 1200), override);
    assert(controller.override.active && controller.override.expires_ms == 2100);
    equal_output(led_controller_resolve(&controller, false, 1, 1500), override);
    base = led_controller_resolve(&controller, false, 1, 2100);
    assert(!controller.override.active);
    equal_output(wireless_status_led_resolve(WIRELESS_STATUS_LED_NORMAL, false, &base, 2100), base);
}

static void test_missing_profile_unknown_mode_and_large_uptime(void)
{
    const struct led_output off = {0, 0, 0, 0, LED_EFFECT_STATIC};
    const struct led_output base = {1, 2, 3, 4, LED_EFFECT_SLOW_BLINK};
    equal_output(wireless_status_led_resolve(WIRELESS_STATUS_LED_NORMAL, false, NULL, 0), off);
    equal_output(wireless_status_led_resolve((enum wireless_status_led_mode)99, false, &base, 0), base);
    equal_output(wireless_status_led_resolve(WIRELESS_STATUS_LED_BLUETOOTH, false, NULL, UINT64_MAX),
        (struct led_output){0, 255, 0, 50, LED_EFFECT_STATIC});
}

int main(void)
{
    test_bluetooth_and_recovery_have_distinct_alternating_colours();
    test_fault_keeps_the_existing_highest_priority_indication();
    test_normal_profiles_and_level_scaling_pass_through();
    test_wireless_overlay_does_not_consume_or_rewrite_override();
    test_missing_profile_unknown_mode_and_large_uptime();
    return 0;
}
