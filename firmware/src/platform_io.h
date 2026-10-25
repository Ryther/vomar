#ifndef VIMAR_PLATFORM_IO_H
#define VIMAR_PLATFORM_IO_H

#include <stdbool.h>
#include <stdint.h>
#include "dimmer_model.h"
#include "led_controller.h"

int platform_io_restore(bool *on, uint8_t *level);
int platform_io_init(bool on, uint8_t level);
int platform_io_apply(bool on, uint8_t level);
bool platform_io_input_settled(void);
int platform_io_request_recovery(void);
void platform_io_tick(uint64_t now);
void platform_io_led(const struct led_output *output, uint64_t now);
const struct dimmer_secondary_capabilities *platform_io_capabilities(void);
void platform_io_render(bool on);

#endif
