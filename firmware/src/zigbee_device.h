#ifndef VIMAR_ZIGBEE_DEVICE_H
#define VIMAR_ZIGBEE_DEVICE_H

#include <stdint.h>
#include <stdbool.h>

int zigbee_device_start(void);
int zigbee_device_prepare_recovery(void);
void zigbee_device_cancel_gestures(void);
void zigbee_device_connection_selector(bool active,uint64_t since_ms);
void zigbee_device_local_edge_at(uint8_t encoded_edge, uint64_t timestamp_ms);
void zigbee_device_local_edge(uint8_t encoded_edge);

#endif
