#include "restore_policy.h"
bool vimar_restore_authorized(bool signature_valid, uint8_t device_id,
 uint32_t selected_offset, size_t signed_size, const uint8_t actual[32],
 const uint8_t expected[32])
{
 if (!signature_valid || device_id != 0 || selected_offset != 0xb0000 ||
     signed_size == 0 || signed_size > 0x3f000 || !actual || !expected) return false;
 uint8_t difference = 0;
 for (size_t i = 0; i < 32; ++i) difference |= actual[i] ^ expected[i];
 return difference == 0;
}
