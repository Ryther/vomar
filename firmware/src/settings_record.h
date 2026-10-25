#ifndef VIMAR_SETTINGS_RECORD_H
#define VIMAR_SETTINGS_RECORD_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "dimmer_config.h"
#define SETTINGS_RECORD_MAX_SIZE 128
enum settings_record_result { SETTINGS_RECORD_OK, SETTINGS_RECORD_BAD_FORMAT,
    SETTINGS_RECORD_BAD_VERSION, SETTINGS_RECORD_BAD_CRC, SETTINGS_RECORD_BAD_CONFIG };
bool settings_record_encode(const struct dimmer_config *, bool, uint8_t,
    uint8_t *, size_t, size_t *);
enum settings_record_result settings_record_decode(const uint8_t *, size_t,
    struct dimmer_config *, bool *, uint8_t *);
#endif
