#ifndef VIMAR_RECOVERY_PRIMARY_H
#define VIMAR_RECOVERY_PRIMARY_H
#include <stddef.h>
#include <stdint.h>
#define RECOVERY_PRIMARY_BASE 0xc000u
#define RECOVERY_PRIMARY_CAPACITY 0xa2000u
/* Full pinned-key signature, vector/slot geometry and protected MAIN role with
 * profile2 identity. Legacy images with no role require one of four exact
 * authenticated digests. An explicit helper role never uses that fallback. */
int recovery_primary_validate(const uint8_t *,size_t capacity);
/* Pairing additionally requires its versioned descriptor in signed MAIN payload. */
int recovery_primary_validate_pairing(const uint8_t *,size_t capacity);
/* Explicit execution only: signed profile2 MIGRATION, exact signed-region
 * hash, same primary geometry. No normal-exit or legacy-role fallback. */
int recovery_primary_validate_migration(const uint8_t *,size_t capacity,const uint8_t expected_hash[32]);
/* A completed upload may contain a normal MAIN or an authenticated profile2
 * MIGRATION. Completion clears partial intent, never authorizes execution. */
int recovery_primary_validate_upload(const uint8_t *,size_t capacity);
#endif
