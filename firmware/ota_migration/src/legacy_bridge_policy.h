#ifndef VIMAR_LEGACY_BRIDGE_POLICY_H
#define VIMAR_LEGACY_BRIDGE_POLICY_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define LEGACY_BRIDGE_CHECKPOINT_SIZE 128u

struct legacy_bridge_identity {
    uint32_t uid[2];
    uint8_t loader_digest[32];
    uint8_t primary_digest[32];
    uint8_t recovery_digest[32];
    uint32_t primary_size;
};

/* Checkpoints detect torn storage, not forgery. The caller must independently
 * authenticate the running primary, exact full 48 KiB loader and embedded
 * replacement recovery before using this policy. recovery_digest hashes the
 * complete signed replacement recovery file; primary_digest uses the OTA
 * transaction's authenticated signed-region digest convention.
 *
 * All functions return 0 on success and -1 on invalid arguments/records.
 * Encode leaves its output untouched on failure; decode clears out on failure.
 */
int legacy_bridge_checkpoint_encode(const struct legacy_bridge_identity *identity,
                                    uint8_t *record, size_t size);
int legacy_bridge_checkpoint_decode(const uint8_t *record, size_t size,
                                    struct legacy_bridge_identity *identity);

/* Absence means exactly NULL/0. A present checkpoint must always match expected,
 * even when a valid transaction exists. Flags are cleared before validation.
 * A successful transaction admission requires checkpoint persistence before
 * transaction deletion; this pure policy performs neither operation itself.
 * The absent-transaction path requires an already matching checkpoint.
 */
int legacy_bridge_admit(const uint8_t *transaction, size_t transaction_size,
                        const uint8_t *checkpoint, size_t checkpoint_size,
                        const struct legacy_bridge_identity *expected,
                        bool *needs_checkpoint, bool *clear_transaction);

#endif
