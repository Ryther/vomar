#ifndef VIMAR_RESTORE_POLICY_H
#define VIMAR_RESTORE_POLICY_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
bool vimar_restore_authorized(bool signature_valid, uint8_t device_id,
 uint32_t selected_offset, size_t signed_size, const uint8_t actual[32],
 const uint8_t expected[32]);
#endif
