#ifndef VIMAR_ZIGBEE_OTA_H
#define VIMAR_ZIGBEE_OTA_H
#include <zboss_api.h>
#include <stdbool.h>
#include <stdint.h>
#include "ota_release.h"
#define VIMAR_OTA_MANUFACTURER VIMAR_OTA_MANUFACTURER_CODE
void zigbee_ota_init(void);
/* Immutable boot-verified signed-region digest, never worker scratch output. */
bool zigbee_ota_recovery_snapshot(uint8_t digest[32]);
void zigbee_ota_joined(void);
void zigbee_ota_callback(zb_bufid_t buffer);
extern zb_zcl_attr_t vimar_ota_attrs[];
/* Fourteen SDK attributes, revision and end sentinel. */
#define VIMAR_OTA_ATTR_COUNT 16
#endif
