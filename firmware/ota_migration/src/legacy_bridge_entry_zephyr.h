#ifndef VIMAR_LEGACY_BRIDGE_ENTRY_ZEPHYR_H
#define VIMAR_LEGACY_BRIDGE_ENTRY_ZEPHYR_H
#include <stdint.h>
int legacy_bridge_prepare(const uint32_t uid[2],const uint8_t loader_digest[32],
                          const uint8_t recovery_digest[32]);
int legacy_bridge_record_recovery_entry(void);
#endif
