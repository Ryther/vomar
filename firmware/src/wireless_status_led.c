#include "wireless_status_led.h"

struct led_output wireless_status_led_resolve(enum wireless_status_led_mode mode,
    bool fault_active, const struct led_output *normal, uint64_t elapsed_ms)
{
    if (fault_active)
        return (struct led_output){255, 0, 0, 100, LED_EFFECT_SLOW_BLINK};

    if (mode == WIRELESS_STATUS_LED_BLUETOOTH || mode == WIRELESS_STATUS_LED_RECOVERY) {
        /* Two adjacent 500 ms phases, without an intervening OFF phase. */
        if (elapsed_ms % 1000 < 500)
            return (struct led_output){0, 0, 255, 50, LED_EFFECT_STATIC};
        return mode == WIRELESS_STATUS_LED_BLUETOOTH
            ? (struct led_output){0, 255, 0, 50, LED_EFFECT_STATIC}
            : (struct led_output){255, 0, 0, 50, LED_EFFECT_STATIC};
    }

    return normal ? *normal : (struct led_output){0, 0, 0, 0, LED_EFFECT_STATIC};
}
