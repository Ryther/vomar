#ifndef VIMAR_WIRELESS_STATUS_LED_H
#define VIMAR_WIRELESS_STATUS_LED_H

#include <stdbool.h>
#include <stdint.h>
#include "led_controller.h"

enum wireless_status_led_mode {
    WIRELESS_STATUS_LED_NORMAL,
    WIRELESS_STATUS_LED_BLUETOOTH,
    WIRELESS_STATUS_LED_RECOVERY,
};

/* Pure display policy, not yet wired into main or recovery firmware.
 * fault_active is authoritative and overrides all wireless and user LED modes.
 * normal is the already resolved user profile/override; it is never modified.
 * elapsed_ms is time since wireless-mode entry, supplied by the caller.
 * The returned slow-blink effect for FAULT is rendered by the existing driver.
 * No timers, hardware IO, lamp state, configuration or persistent data are owned
 * by this function. NORMAL/unknown modes pass through normal, or return OFF when
 * no normal output was supplied. Integration must preserve the independent
 * protection monitor and pass an accurate fault state.
 */
struct led_output wireless_status_led_resolve(enum wireless_status_led_mode mode,
    bool fault_active, const struct led_output *normal, uint64_t elapsed_ms);

#endif
