#ifndef VIMAR_BUTTONS_H
#define VIMAR_BUTTONS_H
#include <stdbool.h>
#include <stdint.h>
struct vimar_buttons {bool initialized,blocked,chord,sent;uint8_t raw,stable;uint64_t raw_since,chord_since;};
struct vimar_button_sample {uint8_t changed,pressed;bool cancel,recovery;};
struct vimar_button_sample vimar_buttons_tick(struct vimar_buttons *,uint64_t,uint8_t);
#endif
