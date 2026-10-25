/* SPDX-License-Identifier: Apache-2.0 */
#include "migration_copy.h"
#include "../../ota/ota_image.h"
#include <errno.h>
#include <string.h>

_Alignas(4) static uint8_t expected_page[MIGRATION_PAGE_SIZE];
static uint8_t read_scratch[64];

int migration_common_loader_authorized(const uint8_t actual[32],
                                      const uint8_t allowed[][32], size_t count)
{
    if (!actual || !allowed || !count || count > 64) return -EINVAL;
    for (size_t i = 0; i < count; ++i)
        if (!memcmp(actual, allowed[i], 32)) return 0;
    return -EACCES;
}

int migration_common_recovery_authorized(const struct ota_image_info *authenticated,
                                        size_t embedded_size)
{
    if (!authenticated || embedded_size < 512 + 4 || embedded_size > 0x34000 ||
        authenticated->output_size != embedded_size ||
        authenticated->authenticated_profile != 2 ||
        authenticated->authenticated_role != OTA_IMAGE_ROLE_RECOVERY) return -EACCES;
    return 0;
}

static void prepare_page(const struct migration_copy_bundle *bundle, size_t offset)
{
    memset(expected_page, 0xff, sizeof(expected_page));
    if (offset < bundle->size) {
        size_t count = bundle->size - offset;
        if (count > sizeof(expected_page)) count = sizeof(expected_page);
        memcpy(expected_page, bundle->data + offset, count);
    }
}

/* 0 means exact match, 1 mismatch, negative means operational read error. */
static int compare_page(const struct migration_copy_io *io, uint32_t address)
{
    for (size_t offset = 0; offset < sizeof(expected_page); offset += sizeof(read_scratch)) {
        int rc = io->read(io->ctx, address + (uint32_t)offset, read_scratch,
                          sizeof(read_scratch));
        if (rc) return rc < 0 ? rc : -EIO;
        if (memcmp(read_scratch, expected_page + offset, sizeof(read_scratch))) return 1;
    }
    return 0;
}

int migration_copy_run(const struct migration_copy_bundle *bundle,
                       const struct migration_copy_io *io)
{
    if (!bundle || !io || !bundle->data || bundle->size < 512 + 4 ||
        bundle->size > MIGRATION_RECOVERY_END - MIGRATION_RECOVERY_START ||
        !io->read_uid || !io->sha256 || !io->verify_image || !io->read ||
        !io->erase || !io->write) return -EINVAL;

    uint32_t actual_uid[2];
    int rc = io->read_uid(io->ctx, actual_uid);
    if (rc) return rc < 0 ? rc : -EIO;
    if (actual_uid[0] != bundle->uid[0] || actual_uid[1] != bundle->uid[1]) return -EACCES;

    uint8_t digest[32];
    rc = io->sha256(io->ctx, bundle->data, bundle->size, digest);
    if (rc) return rc < 0 ? rc : -EIO;
    if (memcmp(digest, bundle->sha256, sizeof(digest))) return -EACCES;
    rc = io->verify_image(io->ctx, bundle->data, bundle->size);
    if (rc) return rc < 0 ? rc : -EIO;

    /* The loop constants are the entire write authority. No address or extent
     * from the signed bundle can broaden it into primary, loader or settings. */
    for (uint32_t address = MIGRATION_RECOVERY_START;
         address < MIGRATION_RECOVERY_END; address += MIGRATION_PAGE_SIZE) {
        prepare_page(bundle, address - MIGRATION_RECOVERY_START);
        rc = compare_page(io, address);
        if (rc < 0) return rc;
        if (rc == 0) continue;
        rc = io->erase(io->ctx, address, MIGRATION_PAGE_SIZE);
        if (rc) return rc < 0 ? rc : -EIO;
        rc = io->write(io->ctx, address, expected_page, sizeof(expected_page));
        if (rc) return rc < 0 ? rc : -EIO;
        rc = compare_page(io, address);
        if (rc) return rc < 0 ? rc : -EIO;
    }
    /* Verify complete signed blob AND erased trailing slot, including pages
     * skipped earlier. Success authorizes the caller's recovery reboot only. */
    for (uint32_t address = MIGRATION_RECOVERY_START;
         address < MIGRATION_RECOVERY_END; address += MIGRATION_PAGE_SIZE) {
        prepare_page(bundle, address - MIGRATION_RECOVERY_START);
        rc = compare_page(io, address);
        if (rc) return rc < 0 ? rc : -EIO;
    }
    return 0;
}
