#ifndef VIMAR_ATTACHMENT_GPIO_H
#define VIMAR_ATTACHMENT_GPIO_H

#include <stdbool.h>
#include <stdint.h>

int vimar_attachment_gpio_init(void);
void vimar_attachment_gpio_cancel(void);
void vimar_attachment_gpio_tick(uint64_t now_ms, bool blocked);

#endif
