#ifndef RESEARCH_STATUS_LED_H
#define RESEARCH_STATUS_LED_H
#include <stdbool.h>
#include <stdint.h>
uint16_t research_status_led_compare(bool authenticated, uint32_t uptime_ms);
int research_status_led_init(void);
void research_status_led_authenticated(bool authenticated);
int research_status_led_tick(uint32_t uptime_ms);
#endif
