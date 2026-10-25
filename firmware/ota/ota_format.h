#ifndef VIMAR_OTA_FORMAT_H
#define VIMAR_OTA_FORMAT_H
#include <stddef.h>
#include <stdint.h>

/* Strict project ZCL OTA header+single upgrade-image subelement header. `size`
 * need only cover the first 66 bytes; expected_total is the transport length.
 * These parsers establish geometry only, never authenticity or install consent.
 * Return zero on success, -1 on malformed/unsupported data. Outputs are cleared
 * on failure. Output pointers must be non-NULL and distinct from input memory.
 */
int ota_container_header(const uint8_t *data, size_t size,
                         uint32_t expected_version, uint32_t expected_total,
                         uint32_t *payload_size);

/* Parse an ordinary MCUboot image mapped within capacity. Padding after the
 * ordinary TLV region is allowed. No trust is placed in hashes or signatures.
 * Signed region includes header, payload and protected TLVs; total includes the
 * ordinary TLV region as well. No compressed image flag is accepted.
 */
int ota_primary_extent(const uint8_t *mapped, size_t capacity,
                       uint32_t *signed_region_size, uint32_t *total_size);
#endif
