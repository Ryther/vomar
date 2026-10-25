#ifndef VIMAR_RECOVERY_IDENTITY_H
#define VIMAR_RECOVERY_IDENTITY_H
#include <stdint.h>
#include <zcbor_encode.h>
/* READ command0 in project SMP group0x8040. Reported runtime identity, not a
 * hardware attestation. Model/layout are firmware compatibility declarations. */
#define VIMAR_IDENTITY_GROUP 0x8040u
bool recovery_identity_encode(zcbor_state_t *, const uint32_t uid[2], const uint8_t loader_sha256[32]);
void recovery_identity_register(void);
#endif
