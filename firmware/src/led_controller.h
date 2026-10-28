#ifndef VIMAR_LED_CONTROLLER_H
#define VIMAR_LED_CONTROLLER_H
#include <stdbool.h>
#include <stdint.h>
#include "dimmer_config.h"
enum led_effect { LED_EFFECT_STATIC, LED_EFFECT_SLOW_BLINK, LED_EFFECT_FAST_BLINK = 2 };
struct led_output { uint8_t r, g, b, intensity; enum led_effect effect; };
struct led_layer { bool active; struct led_output output; uint64_t expires_ms; };
struct led_controller { struct dimmer_config config; bool fault_active; bool identify_active;
    struct led_layer temporary; struct led_layer override; };
void led_controller_init(struct led_controller *, const struct dimmer_config *);
void led_controller_set_fault(struct led_controller *, bool);
void led_controller_set_identifying(struct led_controller *, bool);
void led_controller_set_temporary(struct led_controller *, const struct led_output *, uint64_t, uint32_t);
void led_controller_set_override(struct led_controller *, const struct led_output *, uint64_t, uint32_t);
void led_controller_clear_override(struct led_controller *);
struct led_output led_controller_resolve(struct led_controller *, bool, uint8_t, uint64_t);
#endif
