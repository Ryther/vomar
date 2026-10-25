/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_OTA_INSTALL_H
#define VIMAR_OTA_INSTALL_H
#include <stddef.h>
#include <stdint.h>
#include "ota_transaction.h"

struct ota_install_io {
    /* Contiguous memory-mapped flash, indexed by physical flash address. On
     * nRF52840 mapped is address zero. Host tests use a RAM buffer. */
    const uint8_t *mapped;
    size_t mapped_size;
    void *ctx;
    int (*erase)(void *ctx, uint32_t address, size_t size);
    int (*write)(void *ctx, uint32_t address, const uint8_t *data, size_t size);
    int (*save)(void *ctx, const struct ota_transaction *tx);
    const uint8_t (*allowed_loaders)[32];
    size_t allowed_loader_count;
};
/* Serialized early-boot operation. Returns 1 after persisted completion, zero
 * for inactive transactions, negative error. No IO occurs before dry-run auth.
 * Source, destination and journal must remain exclusively owned for this call. */
int ota_install_run(struct ota_transaction *tx, const struct ota_install_io *io);
/* After settings initialization/load, before starting BLE services. Reboots on
 * successful install; errors return so authenticated BLE recovery can start. */
int ota_install_pending(void);
#endif
