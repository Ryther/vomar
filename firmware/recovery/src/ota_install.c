#if defined(CONFIG_VIMAR_P031_PROTECTION)
#include "boot_trace.h"
#include "vimar_power_protection.h"
#endif
/* SPDX-License-Identifier: Apache-2.0 */
#include "ota_install.h"
#include "ota_image.h"
#include "ota_format.h"
#include "ota_stage.h"
#include "ota_storage.h"
#include "ota_split_stage.h"
#include "ota_pair.h"
#if defined(CONFIG_VIMAR_LOADER_RUNTIME_V2)
#include "loader_runtime_zephyr.h"
#endif
#include <errno.h>
#include <string.h>

/* Static because Zephyr's recovery main thread stack is intentionally small.
 * Installer runs before BLE starts; decoder and page buffer are non-reentrant. */
_Alignas(4) static uint8_t output_page[OTA_STAGE_PAGE_SIZE];
struct writer {
    const struct ota_install_io *io;
    uint32_t expected_offset, page_address, used, erase_limit;
};
static const uint8_t *mapped_at(const struct ota_install_io *io, uint32_t address) {
    return (const uint8_t *)((uintptr_t)io->mapped + address);
}
static int persist_state(struct ota_transaction *tx, const struct ota_install_io *io,
                         enum ota_transaction_state state) {
    if (tx->generation == UINT32_MAX)
        return -EOVERFLOW;
    struct ota_transaction next = *tx;
    next.generation++;
    next.state = state;
    int rc = io->save(io->ctx, &next);
    if (!rc)
        *tx = next;
    return rc;
}
static int flush_page(struct writer *w) {
    if (!w->used)
        return 0;
    if (w->page_address < OTA_PRIMARY_START || w->page_address > w->erase_limit ||
        OTA_STAGE_PAGE_SIZE > w->erase_limit - w->page_address)
        return -EFBIG;
    int rc = w->io->erase(w->io->ctx, w->page_address, OTA_STAGE_PAGE_SIZE);
    if (!rc)
        rc = w->io->write(w->io->ctx, w->page_address, output_page, OTA_STAGE_PAGE_SIZE);
    if (!rc) {
        w->page_address += OTA_STAGE_PAGE_SIZE;
        w->used = 0;
        memset(output_page, 0xff, sizeof(output_page));
    }
    return rc;
}
static int output(void *ctx, uint32_t offset, const uint8_t *data, size_t size) {
    struct writer *w = ctx;
    if (offset != w->expected_offset || size > UINT32_MAX - w->expected_offset)
        return -EINVAL;
    while (size) {
        size_t copy = OTA_STAGE_PAGE_SIZE - w->used;
        if (copy > size)
            copy = size;
        memcpy(output_page + w->used, data, copy);
        w->used += copy;
        w->expected_offset += copy;
        data += copy;
        size -= copy;
        if (w->used == OTA_STAGE_PAGE_SIZE) {
            int rc = flush_page(w);
            if (rc)
                return rc;
        }
    }
    return 0;
}
static int primary_matches(const struct ota_install_io *io, const struct ota_image_info *image,
                           uint32_t capacity) {
    uint8_t digest[32];
    uint32_t region = 0, total = 0;
    const uint8_t *primary = mapped_at(io, OTA_PRIMARY_START);
    if (ota_primary_extent(primary, capacity, &region, &total) || total != image->output_size)
        return 0;
    if (ota_image_sha256(primary, total, digest) || memcmp(digest, image->output_digest, 32))
        return 0;
    if (ota_image_sha256(primary, region, digest) || memcmp(digest, image->signed_digest, 32))
        return 0;
    return 1;
}
static int version_compare(const uint8_t a[8], const uint8_t b[8]) {
    /* MCUboot version components, not bytewise comparison of LE fields. */
    uint32_t av[4] = {a[0], a[1], a[2] | (uint32_t)a[3] << 8,
                      a[4] | (uint32_t)a[5] << 8 | (uint32_t)a[6] << 16 | (uint32_t)a[7] << 24};
    uint32_t bv[4] = {b[0], b[1], b[2] | (uint32_t)b[3] << 8,
                      b[4] | (uint32_t)b[5] << 8 | (uint32_t)b[6] << 16 | (uint32_t)b[7] << 24};
    for (unsigned i = 0; i < 4; i++) {
        if (av[i] != bv[i])
            return av[i] > bv[i] ? 1 : -1;
    }
    return 0;
}
struct split_input {const struct ota_install_io *io;struct ota_split_bounds bounds;};
static int read_split(void*ctx,uint32_t off,uint8_t*p,size_t n) {
 struct split_input *s=ctx;
 while(n){uint32_t physical,available;int rc=ota_split_map(&s->bounds,off,&physical,&available);if(rc)return rc;
  size_t take=n<available?n:available;
  if(physical>s->io->mapped_size||take>s->io->mapped_size-physical)return-EINVAL;
  memcpy(p,mapped_at(s->io,physical),take);off+=take;p+=take;n-=take;}
 return 0;
}
int ota_install_run(struct ota_transaction *tx, const struct ota_install_io *io) {
    if (!tx || !io || !io->erase || !io->write || !io->save || io->mapped_size < OTA_STAGE_END)
        return -EINVAL;
    if (ota_transaction_validate(tx))
        return -EINVAL;
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
    if(tx->format_version!=2)return-EPROTONOSUPPORT;
#elif !defined(OTA_INSTALL_HOST)
    if(tx->format_version!=1)return-EPROTONOSUPPORT;
#endif
    if (tx->state == OTA_TRANSACTION_DOWNLOADING || tx->state == OTA_TRANSACTION_COMPLETE)
        return 0;
    /* Reserve both durable state transitions before touching primary. */
    if (tx->generation > UINT32_MAX - 2)
        return -EOVERFLOW;
    uint32_t capacity = tx->stage_start - OTA_PRIMARY_START;
    const uint8_t *source = mapped_at(io, tx->stage_start);
    struct ota_image_info image;
    struct split_input input={.io=io,.bounds={tx->stage_start,tx->stage_end,tx->second_start,tx->second_end,tx->candidate_size}};
    struct ota_reader reader={.size=tx->candidate_size,.profile=2,.ctx=&input,.read=read_split};
    if(tx->format_version==2){
#if !defined(CONFIG_VIMAR_OTA_SPLIT_STAGING) && !defined(OTA_INSTALL_HOST)
     return-ENOTSUP;
#endif
     uint8_t loader[32];struct ota_image_info recovery;
     /* JournalV2 remains exact full48KiB; typed authority is independent. */
#if defined(CONFIG_VIMAR_LOADER_RUNTIME_V2)
     int pair_rc=loader_pair_verify_zephyr(tx->recovery_digest,loader,&recovery);
#else
     int pair_rc=ota_pair_verify(io->mapped,io->mapped_size,io->allowed_loaders,io->allowed_loader_count,tx->recovery_digest,loader,&recovery);
#endif
     if(pair_rc)return pair_rc;
     if(memcmp(loader,tx->loader_digest,32))return-EACCES;
     if(ota_split_validate(&input.bounds))return-EINVAL;
    }
    int rc = tx->format_version==2?ota_image_validate_reader(&reader,capacity,&image):ota_image_validate(source, tx->candidate_size, capacity, &image);
    if (rc)
        return rc;
    if (image.output_size != tx->signed_image_size ||
        memcmp(image.source_digest, tx->candidate_digest, 32) ||
        memcmp(image.signed_digest, tx->final_digest, 32))
        return -EACCES;
    /* Power may have failed after valid primary readback but before COMPLETE.
     * Match against independently authenticated reconstruction, never a journal
     * hash alone. This avoids re-erasing an already completed update. */
    if (primary_matches(io, &image, capacity)) {
        rc = persist_state(tx, io, OTA_TRANSACTION_COMPLETE);
        return rc ? rc : 1;
    }
    struct ota_image_info current;
    /* A retained authenticated primary is authoritative for antirollback. A
     * partially erased primary cannot authenticate and may be resumed. Exact
     * completed-candidate recognition above intentionally precedes this check. */
    int current_rc = tx->format_version==2?ota_image_verify_primary_for_profile(mapped_at(io,OTA_PRIMARY_START),capacity,2,&current):ota_image_verify_primary(mapped_at(io, OTA_PRIMARY_START), capacity, &current);
    /* A target/profile mismatch is not evidence of interrupted installation.
     * Independently authenticate the other profile before admitting a replay. */
    if(current_rc==-EACCES){
        struct ota_image_info opposite;
        int other=ota_image_verify_primary_for_profile(mapped_at(io,OTA_PRIMARY_START),capacity,tx->format_version==2?1:2,&opposite);
        if(!other)return-EPROTONOSUPPORT;
        if(other!=-EBADMSG&&other!=-EACCES)return other;
    }
    if (current_rc == 0 && version_compare(image.image_version, current.image_version) <= 0)
        return -EPERM;
    /* Crypto backend/resource failures are not proof of an invalid partial
     * primary and must never disable the version gate. */
    if (current_rc && current_rc != -EBADMSG && current_rc != -EACCES)
        return current_rc;
    rc = persist_state(tx, io, OTA_TRANSACTION_INSTALLING);
    if (rc)
        return rc;
    struct writer w = {.io = io, .page_address = OTA_PRIMARY_START, .erase_limit = tx->stage_start};
    memset(output_page, 0xff, sizeof(output_page));
    /* reconstruct repeats source authentication and full dry run before its
     * first output callback. Interrupted installs always replay from byte zero. */
    rc = tx->format_version==2?ota_image_reconstruct_reader(&reader,capacity,output,&w,&image):ota_image_reconstruct(source, tx->candidate_size, capacity, output, &w, &image);
    if (rc)
        return rc;
    if (w.expected_offset != tx->signed_image_size)
        return -EBADMSG;
    rc = flush_page(&w);
    if (rc)
        return rc;
    if (!primary_matches(io, &image, capacity))
        return -EIO;
    rc = persist_state(tx, io, OTA_TRANSACTION_COMPLETE);
    return rc ? rc : 1;
}

#ifndef OTA_INSTALL_HOST
#include <zephyr/device.h>
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
#include VIMAR_OTA_PAIR_BINDINGS_HEADER
#endif
#include <zephyr/drivers/flash.h>
#include <zephyr/retention/bootmode.h>
#include <zephyr/sys/reboot.h>
#include <zephyr/logging/log.h>
LOG_MODULE_REGISTER(vimar_ota_install, LOG_LEVEL_INF);
static const struct device *flash_device;
static int device_erase(void *ctx, uint32_t address, size_t size) {
    (void)ctx;
    return flash_erase(flash_device, address, size);
}
static int device_write(void *ctx, uint32_t address, const uint8_t *data, size_t size) {
    (void)ctx;
    return flash_write(flash_device, address, data, size);
}
static int device_save(void *ctx, const struct ota_transaction *tx) {
    (void)ctx;
    return ota_storage_save(tx);
}
int ota_install_pending(void) {
    struct ota_transaction tx;
    int rc = ota_storage_load(&tx);
    if (rc == -ENOENT || rc == -EINVAL)
        return 0;
    if (rc)
        return rc;
    if (tx.state == OTA_TRANSACTION_DOWNLOADING || tx.state == OTA_TRANSACTION_COMPLETE)
        return 0;
    flash_device = DEVICE_DT_GET(DT_CHOSEN(zephyr_flash_controller));
    if (!device_is_ready(flash_device))
        return -ENODEV;
    const struct ota_install_io io = {.mapped = (const uint8_t *)0,
                                      .mapped_size = 0x100000,
                                      .erase = device_erase,
                                      .write = device_write,
                                      .save = device_save,
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
                                      .allowed_loaders=ota_allowed_loaders,.allowed_loader_count=ota_allowed_loader_count,
#endif
                                      };
    LOG_INF("Checking staged OTA image at 0x%x (%u bytes)", tx.stage_start, tx.candidate_size);
    rc = ota_install_run(&tx, &io);
    if (rc == 1) {
        LOG_INF("OTA installed and verified (%u bytes)", tx.signed_image_size);
        rc = bootmode_clear();
        if (rc)
            return rc;
#if defined(CONFIG_VIMAR_P031_PROTECTION)
        (void)vimar_boot_trace_request(BOOT_REASON_OTA_COMPLETE);
        int protection_rc=vimar_power_protection_flush();
        if(protection_rc)return protection_rc;
#endif
        sys_reboot(SYS_REBOOT_COLD);
        return -EIO;
    }
    if (rc)
        LOG_ERR("OTA install stopped (%d); starting BLE recovery", rc);
    return rc;
}
#endif
