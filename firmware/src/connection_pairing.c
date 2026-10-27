#include "connection_pairing.h"
void connection_pairing_start(struct connection_pairing *p,uint64_t now)
{p->mode=WIRELESS_STATUS_LED_PAIRING;p->since_ms=now;}
bool connection_pairing_tick(struct connection_pairing *p,uint64_t now)
{
 uint64_t elapsed=now-p->since_ms;
 if(p->mode==WIRELESS_STATUS_LED_PAIRING&&elapsed>=CONNECTION_PAIRING_MS){
  p->mode=WIRELESS_STATUS_LED_NORMAL;return true;
 }
 if(p->mode==WIRELESS_STATUS_LED_PAIRED&&elapsed>=CONNECTION_SUCCESS_MS)
  p->mode=WIRELESS_STATUS_LED_NORMAL;
 return false;
}
bool connection_pairing_joined(struct connection_pairing *p,uint64_t now)
{
 if(p->mode!=WIRELESS_STATUS_LED_PAIRING||now-p->since_ms>=CONNECTION_PAIRING_MS)return false;
 p->mode=WIRELESS_STATUS_LED_PAIRED;p->since_ms=now;return true;
}
enum wireless_status_led_mode connection_pairing_mode(const struct connection_pairing *p)
{return p->mode;}
