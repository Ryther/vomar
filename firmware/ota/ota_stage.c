#include "ota_stage.h"
#include <errno.h>
#include <string.h>

static uint32_t page_up(uint32_t value)
{
    /* Callers first establish value <= OTA_STAGE_END, avoiding overflow. */
    return (value + OTA_STAGE_PAGE_SIZE - 1) & ~(OTA_STAGE_PAGE_SIZE - 1);
}

int ota_stage_plan(uint32_t current_end, uint32_t payload_size,
                   uint32_t destination_end, struct ota_stage_bounds *out)
{
    if (!out || current_end < OTA_PRIMARY_START ||
        current_end > OTA_STAGE_END || destination_end < OTA_PRIMARY_START ||
        destination_end > OTA_STAGE_END || !payload_size ||
        payload_size > OTA_STAGE_END - OTA_PRIMARY_START) {
        return -EINVAL;
    }
    uint32_t start = (OTA_STAGE_END - payload_size) & ~(OTA_STAGE_PAGE_SIZE - 1);
    if (start < page_up(current_end) || start < page_up(destination_end)) {
        return -ENOSPC;
    }
    *out = (struct ota_stage_bounds){start, OTA_STAGE_END, payload_size};
    return 0;
}

int ota_stage_accept(struct ota_stage_transfer *s, uint32_t offset,
                     const uint8_t *data, size_t len)
{
    if (!s || !data || !len || !s->read || !s->write ||
        s->bounds.start < OTA_PRIMARY_START ||
        s->bounds.start >= OTA_STAGE_END || s->bounds.end != OTA_STAGE_END ||
        (s->bounds.start & (OTA_STAGE_PAGE_SIZE - 1)) ||
        !s->bounds.payload_size ||
        s->bounds.payload_size > s->bounds.end - s->bounds.start ||
        s->next_offset > s->bounds.payload_size ||
        offset > s->bounds.payload_size || len > s->bounds.payload_size - offset) {
        return -EINVAL;
    }
    if (offset > s->next_offset) return -EAGAIN;
    if (offset < s->next_offset) {
        if (len > s->next_offset - offset) return -EINVAL;
        uint8_t existing[64];
        size_t compared = 0;
        while (compared < len) {
            size_t count = len - compared;
            if (count > sizeof(existing)) count = sizeof(existing);
            int rc = s->read(s->context, s->bounds.start + offset + (uint32_t)compared,
                             existing, count);
            if (rc) return rc < 0 ? rc : -EIO;
            if (memcmp(existing, data + compared, count)) return -EILSEQ;
            compared += count;
        }
        return 0;
    }
    int rc = s->write(s->context, s->bounds.start + offset, data, len);
    if (rc) return rc < 0 ? rc : -EIO;
    s->next_offset += (uint32_t)len;
    return 0;
}
