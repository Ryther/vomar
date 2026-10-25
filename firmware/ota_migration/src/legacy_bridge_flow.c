#include "legacy_bridge_flow.h"
#include "ota_transaction.h"
#include <errno.h>
#include <string.h>

static int callback_result(int result)
{
    return result > 0 ? -EIO : result;
}

static int load_record(const struct legacy_bridge_flow_io *io,
                       enum legacy_bridge_key key, uint8_t *record,
                       size_t capacity, size_t *size)
{
    *size = SIZE_MAX;
    int rc = callback_result(io->load(io->ctx, key, record, capacity, size));
    if (rc) return rc;
    return *size > capacity ? -EIO : 0;
}

int legacy_bridge_flow_prepare(const struct legacy_bridge_identity *expected,
                               const struct legacy_bridge_flow_io *io)
{
    uint8_t transaction[OTA_TRANSACTION_MAX_RECORD_SIZE];
    uint8_t checkpoint[LEGACY_BRIDGE_CHECKPOINT_SIZE];
    uint8_t encoded[LEGACY_BRIDGE_CHECKPOINT_SIZE];
    size_t transaction_size, checkpoint_size;
    bool needs_checkpoint, clear_transaction;

    if (!io || !io->load || !io->save_checkpoint || !io->clear_transaction ||
        !io->verify_legacy_recovery || !io->clear_boot_request ||
        legacy_bridge_checkpoint_encode(expected, encoded, sizeof(encoded)))
        return -EINVAL;

    int rc = load_record(io, LEGACY_BRIDGE_TRANSACTION, transaction,
                         sizeof(transaction), &transaction_size);
    if (rc) return rc;
    rc = load_record(io, LEGACY_BRIDGE_CHECKPOINT, checkpoint,
                     sizeof(checkpoint), &checkpoint_size);
    if (rc) return rc;
    if (legacy_bridge_admit(transaction_size ? transaction : NULL, transaction_size,
                            checkpoint_size ? checkpoint : NULL, checkpoint_size,
                            expected, &needs_checkpoint, &clear_transaction))
        return -EPERM;

    if (needs_checkpoint) {
        rc = callback_result(io->verify_legacy_recovery(io->ctx));
        if (rc) return rc;
        rc = callback_result(io->save_checkpoint(io->ctx, encoded, sizeof(encoded)));
        if (rc) return rc;
        rc = load_record(io, LEGACY_BRIDGE_CHECKPOINT, checkpoint,
                         sizeof(checkpoint), &checkpoint_size);
        if (rc) return rc;
        /* Exact equality to the canonical authenticated identity checks every
         * field and CRC, including a successful save that retained wrong bytes. */
        if (checkpoint_size != sizeof(encoded) || memcmp(checkpoint, encoded, sizeof(encoded)))
            return -EIO;
    }

    if (clear_transaction) {
        rc = callback_result(io->clear_transaction(io->ctx));
        if (rc) return rc;
        rc = load_record(io, LEGACY_BRIDGE_TRANSACTION, transaction,
                         sizeof(transaction), &transaction_size);
        if (rc) return rc;
        if (transaction_size) return -EIO;
    }

    return callback_result(io->clear_boot_request(io->ctx));
}
