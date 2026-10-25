#ifndef VIMAR_LED_H
#define VIMAR_LED_H
#include "led_controller.h"
int vimar_led_init(void);
int vimar_led_render(const struct led_output *,uint64_t);
#endif
