#ifndef VIMAR_RECOVERY_MIGRATION_H
#define VIMAR_RECOVERY_MIGRATION_H
#include <stdint.h>
#include <zcbor_decode.h>
#include <zcbor_encode.h>
#define VIMAR_MIGRATION_GROUP 0x8042u
/* One WRITE0 with exactly {"hash": bstr32}. Ordinary MCUboot signed-region
 * hash, not complete-file hash. No role selection or legacy authorization. */
bool recovery_migration_decode(zcbor_state_t *,uint8_t expected_hash[32]);
bool recovery_migration_encode_accepted(zcbor_state_t *);
void recovery_migration_register(void);
/* Read-only local OTA-journal/protected-handoff admission; does not consume
 * the handoff or authorize a role. Repeated before executing the helper. */
int recovery_migration_preflight(void);
#endif
