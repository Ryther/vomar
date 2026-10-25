#include "ota_format.h"

static uint16_t u16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}
static uint32_t u32(const uint8_t *p)
{
    return (uint32_t)u16(p) | ((uint32_t)u16(p + 2) << 16);
}

int ota_container_header(const uint8_t *data, size_t size,
                         uint32_t expected_version, uint32_t expected_total,
                         uint32_t *payload_size)
{
    if (!payload_size) return -1;
    *payload_size = 0;
    if (!data || size < 66 || u32(data) != 0x0beef11eu ||
        u16(data + 4) != 0x0100 || u16(data + 6) != 60 ||
        u16(data + 8) != 4 || u16(data + 10) != 0xfff1 ||
        u16(data + 12) != 0x3085 || u32(data + 14) != expected_version ||
        u16(data + 18) != 2 || u32(data + 52) != expected_total ||
        u16(data + 56) != 1 || u16(data + 58) != 1 || u16(data + 60) != 0)
        return -1;
    uint32_t payload = u32(data + 62);
    if (!payload || expected_total < 66 || payload != expected_total - 66)
        return -1;
    *payload_size = payload;
    return 0;
}

int ota_primary_extent(const uint8_t *mapped, size_t capacity,
                       uint32_t *signed_region_size, uint32_t *total_size)
{
    if (!signed_region_size || !total_size || signed_region_size == total_size)
        return -1;
    *signed_region_size = 0;
    *total_size = 0;
    if (!mapped || capacity < 32 || u32(mapped) != 0x96f3b83du ||
        (u32(mapped + 16) & 0xe00u)) return -1;
    uint32_t header = u16(mapped + 8), protected_size = u16(mapped + 10);
    uint32_t image_size = u32(mapped + 12);
    if (header < 32 || header > capacity || !image_size ||
        image_size > UINT32_MAX - header || image_size > capacity - header)
        return -1;
    uint32_t end = header + image_size;
    if (protected_size) {
        if (protected_size < 4 || protected_size > UINT32_MAX - end ||
            protected_size > capacity - end || u16(mapped + end) != 0x6908 ||
            u16(mapped + end + 2) != protected_size) return -1;
        end += protected_size;
    }
    if (capacity - end < 4 || u16(mapped + end) != 0x6907) return -1;
    uint32_t ordinary_size = u16(mapped + end + 2);
    if (ordinary_size < 4 || ordinary_size > UINT32_MAX - end ||
        ordinary_size > capacity - end) return -1;
    *signed_region_size = end;
    *total_size = end + ordinary_size;
    return 0;
}
