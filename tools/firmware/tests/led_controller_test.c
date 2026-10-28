#include <assert.h>
#include <string.h>
#include "led_controller.h"

static void test_profiles_and_level_scaling(void)
{
    struct dimmer_config config = dimmer_config_defaults();
    struct led_controller controller;
    led_controller_init(&controller, &config);
    struct led_output out = led_controller_resolve(&controller, false, 100, 0);
    assert(out.b == 255 && out.intensity == 10);
    out = led_controller_resolve(&controller, true, 100, 0);
    assert(out.g == 255 && out.intensity == 10);

    config.led_on_intensity_mode = DIMMER_LED_INTENSITY_FOLLOW_LEVEL;
    config.led_on_min_intensity = 20; config.led_on_max_intensity = 80;
    led_controller_init(&controller, &config);
    assert(led_controller_resolve(&controller, true, 1, 0).intensity == 20);
    assert(led_controller_resolve(&controller, true, 254, 0).intensity == 80);
    config.led_on_intensity_mode = DIMMER_LED_INTENSITY_INVERSE_LEVEL;
    led_controller_init(&controller, &config);
    assert(led_controller_resolve(&controller, true, 1, 0).intensity == 80);
    assert(led_controller_resolve(&controller, true, 254, 0).intensity == 20);
}

static void test_layer_priority_and_expiry(void)
{
    struct dimmer_config config = dimmer_config_defaults();
    struct led_controller controller;
    struct led_output red = {255, 0, 0, 70, LED_EFFECT_STATIC};
    struct led_output white = {255, 255, 255, 90, LED_EFFECT_SLOW_BLINK};
    led_controller_init(&controller, &config);
    led_controller_set_temporary(&controller, &red, 1000, 500);
    assert(led_controller_resolve(&controller, true, 100, 1200).r == 255);
    led_controller_set_override(&controller, &white, 1200, 500);
    assert(led_controller_resolve(&controller, true, 100, 1699).r == 255);
    assert(led_controller_resolve(&controller, true, 100, 1700).r == 0);
    led_controller_set_override(&controller, &white, 1700, 0);
    led_controller_set_fault(&controller, true);
    assert(led_controller_resolve(&controller, true, 100, 2000).r == 255);
    assert(led_controller_resolve(&controller, true, 100, 2000).effect == LED_EFFECT_SLOW_BLINK);
    led_controller_set_fault(&controller, false);
    led_controller_clear_override(&controller);
    assert(led_controller_resolve(&controller, true, 100, 2000).g == 255);
}

static void assert_identify_output(struct led_output output)
{
    assert(output.r == 0 && output.g == 255 && output.b == 0);
    assert(output.intensity == 100 && output.effect == LED_EFFECT_FAST_BLINK);
}

static void test_identify_priority_and_override_restoration(void)
{
    struct dimmer_config config = dimmer_config_defaults();
    struct led_controller controller;
    struct led_output custom = {23, 45, 67, 80, LED_EFFECT_STATIC};
    led_controller_init(&controller, &config);
    led_controller_set_override(&controller, &custom, 1000, 3000);
    struct led_layer saved_override = controller.override;
    struct dimmer_config saved_config = controller.config;

    led_controller_set_identifying(&controller, true);
    assert_identify_output(led_controller_resolve(&controller, false, 1, 1500));
    assert_identify_output(led_controller_resolve(&controller, true, 254, 1600));
    led_controller_set_fault(&controller, true);
    struct led_output output = led_controller_resolve(&controller, true, 100, 1700);
    assert(output.r == 255 && output.g == 0 && output.b == 0);
    assert(output.intensity == 100 && output.effect == LED_EFFECT_SLOW_BLINK);
    led_controller_set_fault(&controller, false);
    assert_identify_output(led_controller_resolve(&controller, true, 100, 1800));
    led_controller_set_identifying(&controller, false);
    output = led_controller_resolve(&controller, true, 100, 1900);
    assert(output.r == 23 && output.g == 45 && output.b == 67);
    assert(output.intensity == 80 && output.effect == LED_EFFECT_STATIC);
    assert(memcmp(&controller.override, &saved_override, sizeof(saved_override)) == 0);
    assert(memcmp(&controller.config, &saved_config, sizeof(saved_config)) == 0);

    /* Repeated Identify refreshes never renew a user's finite override. */
    led_controller_set_identifying(&controller, true);
    assert_identify_output(led_controller_resolve(&controller, false, 1, 4500));
    led_controller_set_identifying(&controller, true);
    led_controller_set_identifying(&controller, false);
    output = led_controller_resolve(&controller, false, 1, 4500);
    assert(output.r == config.led_off.r && output.g == config.led_off.g);
    assert(output.b == config.led_off.b && output.intensity == config.led_off.intensity);
    assert(output.effect == LED_EFFECT_STATIC);
}

static void test_identify_preserves_temporary_expiry(void)
{
    struct dimmer_config config = dimmer_config_defaults();
    struct led_controller controller;
    struct led_output custom = {10, 20, 30, 40, LED_EFFECT_SLOW_BLINK};
    led_controller_init(&controller, &config);
    led_controller_set_temporary(&controller, &custom, 1000, 1000);
    struct led_layer saved_temporary = controller.temporary;
    led_controller_set_identifying(&controller, true);
    assert_identify_output(led_controller_resolve(&controller, true, 100, 1200));
    led_controller_set_identifying(&controller, false);
    struct led_output output = led_controller_resolve(&controller, true, 100, 1500);
    assert(output.r == 10 && output.g == 20 && output.b == 30);
    assert(output.intensity == 40 && output.effect == LED_EFFECT_SLOW_BLINK);
    assert(memcmp(&controller.temporary, &saved_temporary, sizeof(saved_temporary)) == 0);
    led_controller_set_identifying(&controller, true);
    assert_identify_output(led_controller_resolve(&controller, true, 100, 2500));
    led_controller_set_identifying(&controller, false);
    output = led_controller_resolve(&controller, true, 100, 2500);
    assert(output.r == config.led_on.r && output.g == config.led_on.g);
    assert(output.b == config.led_on.b && output.intensity == config.led_on.intensity);
    assert(output.effect == LED_EFFECT_STATIC);
}

int main(void)
{
    test_profiles_and_level_scaling();
    test_layer_priority_and_expiry();
    test_identify_priority_and_override_restoration();
    test_identify_preserves_temporary_expiry();
    return 0;
}
