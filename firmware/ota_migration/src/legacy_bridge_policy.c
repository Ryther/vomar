#include "legacy_bridge_policy.h"
#include "ota_transaction.h"
#include <string.h>

#define CHECKPOINT_MAGIC 0x3143424cu /* LBC1, little endian */
#define CHECKPOINT_VERSION 1u
#define PRIMARY_CAPACITY (0xae000u - 0xc000u)

static void put32(uint8_t *p, uint32_t value)
{
    for (unsigned i = 0; i < 4; ++i) p[i] = (uint8_t)(value >> (8 * i));
}

static uint32_t get32(const uint8_t *p)
{
    uint32_t value = 0;
    for (unsigned i = 0; i < 4; ++i) value |= (uint32_t)p[i] << (8 * i);
    return value;
}

static uint32_t crc32(const uint8_t *record, size_t size)
{
    uint32_t crc = UINT32_MAX;
    for (size_t i = 0; i < size; ++i) {
        crc ^= record[i];
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1u)));
    }
    return ~crc;
}

static bool identity_valid(const struct legacy_bridge_identity *identity)
{
    const uint8_t zero[32] = {0};
    return identity &&
        (identity->uid[0] || identity->uid[1]) &&
        (identity->uid[0] != UINT32_MAX || identity->uid[1] != UINT32_MAX) &&
        identity->primary_size && identity->primary_size <= PRIMARY_CAPACITY &&
        memcmp(identity->loader_digest, zero, 32) &&
        memcmp(identity->primary_digest, zero, 32) &&
        memcmp(identity->recovery_digest, zero, 32);
}

static bool identity_matches(const struct legacy_bridge_identity *left,
                             const struct legacy_bridge_identity *right)
{
    return left->uid[0] == right->uid[0] && left->uid[1] == right->uid[1] &&
        left->primary_size == right->primary_size &&
        !memcmp(left->loader_digest, right->loader_digest, 32) &&
        !memcmp(left->primary_digest, right->primary_digest, 32) &&
        !memcmp(left->recovery_digest, right->recovery_digest, 32);
}

int legacy_bridge_checkpoint_encode(const struct legacy_bridge_identity *identity,
                                    uint8_t *record, size_t size)
{
    if (!identity_valid(identity) || !record || size != LEGACY_BRIDGE_CHECKPOINT_SIZE)
        return -1;
    put32(record, CHECKPOINT_MAGIC);
    put32(record + 4, CHECKPOINT_VERSION);
    put32(record + 8, LEGACY_BRIDGE_CHECKPOINT_SIZE);
    put32(record + 12, 0);
    put32(record + 16, identity->uid[0]);
    put32(record + 20, identity->uid[1]);
    memcpy(record + 24, identity->loader_digest, 32);
    memcpy(record + 56, identity->primary_digest, 32);
    memcpy(record + 88, identity->recovery_digest, 32);
    put32(record + 120, identity->primary_size);
    put32(record + 124, crc32(record, 124));
    return 0;
}

int legacy_bridge_checkpoint_decode(const uint8_t *record, size_t size,
                                    struct legacy_bridge_identity *identity)
{
    if (!identity) return -1;
    memset(identity, 0, sizeof(*identity));
    if (!record || size != LEGACY_BRIDGE_CHECKPOINT_SIZE ||
        get32(record) != CHECKPOINT_MAGIC ||
        get32(record + 4) != CHECKPOINT_VERSION ||
        get32(record + 8) != LEGACY_BRIDGE_CHECKPOINT_SIZE ||
        get32(record + 12) != 0 || get32(record + 124) != crc32(record, 124))
        return -1;
    struct legacy_bridge_identity decoded = {
        .uid = {get32(record + 16), get32(record + 20)},
        .primary_size = get32(record + 120),
    };
    memcpy(decoded.loader_digest, record + 24, 32);
    memcpy(decoded.primary_digest, record + 56, 32);
    memcpy(decoded.recovery_digest, record + 88, 32);
    if (!identity_valid(&decoded)) return -1;
    *identity = decoded;
    return 0;
}

int legacy_bridge_admit(const uint8_t *transaction, size_t transaction_size,
                        const uint8_t *checkpoint, size_t checkpoint_size,
                        const struct legacy_bridge_identity *expected,
                        bool *needs_checkpoint, bool *clear_transaction)
{
    if (needs_checkpoint) *needs_checkpoint = false;
    if (clear_transaction) *clear_transaction = false;
    if (!needs_checkpoint || !clear_transaction || needs_checkpoint == clear_transaction ||
        !identity_valid(expected) ||
        (!transaction != !transaction_size) || (!checkpoint != !checkpoint_size))
        return -1;

    if (checkpoint) {
        struct legacy_bridge_identity retained;
        if (legacy_bridge_checkpoint_decode(checkpoint, checkpoint_size, &retained) ||
            !identity_matches(&retained, expected)) return -1;
    }
    if (!transaction) return checkpoint ? 0 : -1;

    struct ota_transaction decoded;
    if (ota_transaction_decode(transaction, transaction_size, &decoded) ||
        decoded.format_version != OTA_TRANSACTION_VERSION ||
        decoded.state < OTA_TRANSACTION_PENDING || decoded.state > OTA_TRANSACTION_COMPLETE ||
        decoded.signed_image_size != expected->primary_size ||
        memcmp(decoded.final_digest, expected->primary_digest, 32)) return -1;

    *needs_checkpoint = !checkpoint;
    *clear_transaction = true;
    return 0;
}
