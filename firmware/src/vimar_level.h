#ifndef VIMAR_LEVEL_H
#define VIMAR_LEVEL_H
#include <stdbool.h>
#include <stdint.h>
bool vimar_level_encode(bool on, uint8_t level, int32_t *raw);
bool vimar_level_decode(int32_t raw, bool *on, uint8_t *level);
#endif
