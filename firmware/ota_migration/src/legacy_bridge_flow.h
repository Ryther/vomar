#ifndef VIMAR_LEGACY_BRIDGE_FLOW_H
#define VIMAR_LEGACY_BRIDGE_FLOW_H

#include "legacy_bridge_policy.h"

enum legacy_bridge_key {
    LEGACY_BRIDGE_TRANSACTION,
    LEGACY_BRIDGE_CHECKPOINT,
};

struct legacy_bridge_flow_io {
    void *ctx;
    /* Return 0 and set out_len to 0 for absence. Never return more than capacity
     * bytes. Adapter must normalize its storage API's missing-record result. */
    int (*load)(void *ctx, enum legacy_bridge_key key, uint8_t *record,
                size_t capacity, size_t *out_len);
    int (*save_checkpoint)(void *ctx, const uint8_t *record, size_t size);
    int (*clear_transaction)(void *ctx);
    int (*verify_legacy_recovery)(void *ctx);
    int (*clear_boot_request)(void *ctx);
};

/* Caller authenticates the executing primary, actual full48KiB loader and
 * complete embedded replacement recovery before calling. A fresh checkpoint
 * also requires verify_legacy_recovery to authenticate the current legacy REC.
 * A retained matching checkpoint permits interrupted replacement of that REC.
 *
 * This function only prepares persistent authorization. It never writes REC.
 * Caller may begin the resumable REC copy only after return0. On error it must
 * stop, including when a callback failed after committing its operation. Retry
 * using the same authenticated identity and retained records.
 *
 * All callbacks are required. Negative callback errors propagate; positive
 * statuses are normalized to -EIO. Bad arguments/records return negative errno.
 * The caller must serialize this operation against changes to these records.
 */
int legacy_bridge_flow_prepare(const struct legacy_bridge_identity *expected,
                               const struct legacy_bridge_flow_io *io);

#endif
