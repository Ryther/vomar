#ifndef VIMAR_PLATFORM_IO_H
#define VIMAR_PLATFORM_IO_H

#include <stdbool.h>
#include <stdint.h>
#include "dimmer_model.h"
#include "led_controller.h"

int platform_io_restore(bool *on, uint8_t *level);
int platform_io_init(bool on, uint8_t level);
/* Failed startup explicitly disabled the gate; not physical feedback. */
bool platform_io_startup_inhibited(void);
int platform_io_apply(bool on, uint8_t level);
int platform_io_check_phase_cut(enum dimmer_phase_cut_mode);
int platform_io_set_phase_cut(enum dimmer_phase_cut_mode);
bool platform_io_input_settled(void);
int platform_io_request_recovery(void);
int platform_io_request_pairing(void);
void platform_io_tick(uint64_t now);
void platform_io_cancel_attachment(void);
void platform_io_led(const struct led_output *output, uint64_t now);
const struct dimmer_secondary_capabilities *platform_io_capabilities(void);
void platform_io_render(bool on);

#endif
