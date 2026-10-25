/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_MIGRATION_COPY_H
#define VIMAR_MIGRATION_COPY_H
#include <stddef.h>
#include <stdint.h>

#define MIGRATION_RECOVERY_START UINT32_C(0xb0000)
#define MIGRATION_RECOVERY_END UINT32_C(0xf0000)
#define MIGRATION_PAGE_SIZE UINT32_C(4096)

struct migration_copy_bundle {
    uint32_t uid[2]; /* Exact FICR DEVICEID words, in register order. */
    const uint8_t *data; /* Embedded in the authenticated, immutable primary. */
    size_t size;         /* Exact signed recovery extent, excluding erased tail. */
    uint8_t sha256[32];  /* SHA256 of all size bytes, including ordinary TLVs. */
};
struct migration_copy_io {
    void *ctx;
    int (*read_uid)(void *ctx, uint32_t actual_uid[2]);
    int (*sha256)(void *ctx, const uint8_t *data, size_t size, uint8_t digest[32]);
    /* Mandatory: authenticate recovery with the loader's pinned signing key,
     * including complete signed extent == size. Zero success, negative failure.
     * Production wrapper uses ota_image_verify_primary, not a hash-only check. */
    int (*verify_image)(void *ctx, const uint8_t *data, size_t size);
    int (*read)(void *ctx, uint32_t address, uint8_t *out, size_t size);
    int (*erase)(void *ctx, uint32_t address, size_t size);
    int (*write)(void *ctx, uint32_t address, const uint8_t *data, size_t size);
};
struct ota_image_info;
/* Common-mode guards consume a hash of actual FLASH0..0xc000 and metadata
 * published by a successful pinned-key image verifier. Neither grants writes. */
int migration_common_loader_authorized(const uint8_t actual[32],
                                      const uint8_t allowed[][32], size_t count);
int migration_common_recovery_authorized(const struct ota_image_info *authenticated,
                                        size_t embedded_size);
/* Call only from a bootloader-authenticated migration primary. Bundle data and
 * manifest are immutable until return; serialize against BLE and all flash IO.
 * UID/hash/signature are checked on EVERY attempt before any flash mutation.
 * Only recovery pages b0000..f0000 are erased/written. Matching pages are skipped;
 * all bytes after the signed recovery extent are required to be erased (FF).
 * Returns 0 only after final full recovery-range readback; negative error stops
 * immediately. Re-run after failure/reset from the unchanged signed primary.
 * No bootmode changes, persistent flags, reboot or primary invalidation occur.
 * Caller may clear bootmode/reboot only after successful completion.
 * Static page/scratch buffers make this function non-reentrant. */
int migration_copy_run(const struct migration_copy_bundle *bundle,
                       const struct migration_copy_io *io);
#endif
