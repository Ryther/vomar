#ifndef VIMAR_OTA_STAGE_H
#define VIMAR_OTA_STAGE_H

#include <stddef.h>
#include <stdint.h>

#define OTA_PRIMARY_START UINT32_C(0xc000)
#define OTA_PRIMARY_END UINT32_C(0xb0000)
#define OTA_STAGE_END UINT32_C(0xae000)
#define OTA_STAGE_PAGE_SIZE UINT32_C(4096)

/* All addresses are physical, end-exclusive. Only payload_size bytes starting
 * at start belong to the transfer; end includes page padding. */
struct ota_stage_bounds {
    uint32_t start;
    uint32_t end;
    uint32_t payload_size;
};

/* current_end and destination_end include their complete signed image metadata.
 * Both are rounded up to erase pages before checking source separation.
 * Returns zero or negative errno; failure leaves out unchanged. */
int ota_stage_plan(uint32_t current_end, uint32_t payload_size,
                   uint32_t destination_end, struct ota_stage_bounds *out);

typedef int (*ota_stage_read_fn)(void *context, uint32_t address,
                                  uint8_t *data, size_t len);
typedef int (*ota_stage_write_fn)(void *context, uint32_t address,
                                   const uint8_t *data, size_t len);

/* Initialize with planned bounds, next_offset=0 and both callbacks. IO must be
 * synchronous, return zero on success or a negative errno, and never erase
 * outside the planned pages. Prepare erased pages separately before download.
 * The caller serializes access. A failed write may have partially programmed
 * bytes: next_offset remains unchanged, so flash adapters must safely retry or
 * abort/restart the download. This is accounting, not durable journaling. */
struct ota_stage_transfer {
    struct ota_stage_bounds bounds;
    uint32_t next_offset;
    ota_stage_read_fn read;
    ota_stage_write_fn write;
    void *context;
};

/* Matching complete retransmissions succeed without writes. Gaps return
 * -EAGAIN (request next_offset); conflicting duplicates return -EILSEQ.
 * Partial overlap, empty blocks and invalid intervals return -EINVAL. */
int ota_stage_accept(struct ota_stage_transfer *s, uint32_t offset,
                     const uint8_t *data, size_t len);
#endif
