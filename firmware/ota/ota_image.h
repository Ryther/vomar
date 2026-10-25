/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_OTA_IMAGE_H
#define VIMAR_OTA_IMAGE_H
#include <stddef.h>
#include <stdint.h>
#include "ota_reader.h"

/* Protected MCUboot custom TLV 0xa1, exactly one byte. NONE is absence of
 * legacy metadata, never a valid encoded role. Model/profile remains TLV 0xa0. */
enum ota_image_role {
    OTA_IMAGE_ROLE_NONE = 0,
    OTA_IMAGE_ROLE_MAIN = 1,
    OTA_IMAGE_ROLE_RECOVERY = 2,
    OTA_IMAGE_ROLE_MIGRATION = 3,
    OTA_IMAGE_ROLE_RESTORE = 4,
    OTA_IMAGE_ROLE_DIAGNOSTIC = 5,
};

struct ota_image_info {
    uint32_t output_size;
    uint8_t image_version[8];
    uint8_t source_digest[32]; /* Complete staged file. */
    uint8_t output_digest[32]; /* Complete ordinary image; zero after authenticate only. */
    uint8_t signed_digest[32]; /* Ordinary MCUboot signed region, used by journal. */
    /* Published only after successful cryptographic verification. Zero means
     * absent legacy metadata. Callers must still check the function result. */
    uint8_t authenticated_role;
    uint8_t authenticated_profile;
};
typedef int (*ota_image_write_fn)(void *ctx, uint32_t offset, const uint8_t *data, size_t size);
int ota_image_sha256(const uint8_t *data, size_t size, uint8_t out[32]);
/* Verify an ordinary signed primary using the pinned key. Capacity may include
 * erased trailing slot bytes. Legacy primaries without target TLV are accepted
 * for comparison during initial migration; compressed candidates always require
 * the exact protected target identity. */
int ota_image_verify_primary(const uint8_t *source, size_t capacity, struct ota_image_info *out);
/* No decompression; proves compressed signature and protected metadata signatures.
 * Suitable for main download CHECK. Validation in recovery is still mandatory. */
int ota_image_authenticate(const uint8_t *source, size_t size, uint32_t output_limit,
                           struct ota_image_info *out);
/* Full authenticated decoder dry run. Source must remain immutable through replay.
 * These APIs use static SDK decoder state and MUST be serialized by caller. */
int ota_image_validate(const uint8_t *source, size_t size, uint32_t output_limit,
                       struct ota_image_info *out);
/* Repeats authenticated dry-run BEFORE the first write callback, then streams the
 * complete ordinary signed image. Caller bounds and page-buffers flash writes.
 * This API performs no flash erase or writes directly. */
int ota_image_reconstruct(const uint8_t *source, size_t size, uint32_t output_limit,
                          ota_image_write_fn write, void *ctx, struct ota_image_info *out);
int ota_image_verify_primary_for_profile(const uint8_t*,size_t,unsigned,struct ota_image_info*);
int ota_image_reader_sha256(const struct ota_reader*,uint32_t,size_t,uint8_t[32]);
int ota_image_authenticate_reader(const struct ota_reader*,uint32_t,struct ota_image_info*);
int ota_image_validate_reader(const struct ota_reader*,uint32_t,struct ota_image_info*);
int ota_image_reconstruct_reader(const struct ota_reader*,uint32_t,ota_image_write_fn,void*,struct ota_image_info*);
#endif
