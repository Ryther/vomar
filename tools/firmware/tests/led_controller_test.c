#include <assert.h>
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

int main(void) { test_profiles_and_level_scaling(); test_layer_priority_and_expiry(); return 0; }
