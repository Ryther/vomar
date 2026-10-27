#ifndef VIMAR_CONNECTION_PAIRING_H
#define VIMAR_CONNECTION_PAIRING_H
#include "wireless_status_led.h"
#define CONNECTION_PAIRING_MS 120000u
#define CONNECTION_SUCCESS_MS 3000u
struct connection_pairing {
 enum wireless_status_led_mode mode;
 uint64_t since_ms;
};
void connection_pairing_start(struct connection_pairing *,uint64_t now_ms);
/* True exactly once when active pairing expires; caller must stop stack retries. */
bool connection_pairing_tick(struct connection_pairing *,uint64_t now_ms);
bool connection_pairing_joined(struct connection_pairing *,uint64_t now_ms);
enum wireless_status_led_mode connection_pairing_mode(const struct connection_pairing *);
#endif
