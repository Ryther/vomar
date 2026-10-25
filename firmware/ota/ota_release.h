#ifndef VIMAR_OTA_RELEASE_H
#define VIMAR_OTA_RELEASE_H
#include <stdint.h>
/* Project-local test manufacturer identifier; not a Vimar-assigned identity. */
#define VIMAR_OTA_MANUFACTURER_CODE 0xfff1u
#define VIMAR_OTA_IMAGE_TYPE 0x3085u
#define VIMAR_OTA_HARDWARE_VERSION 1u
#define VIMAR_OTA_HEADER_SIZE 60u
#define VIMAR_OTA_ENVELOPE_SIZE 66u
/* MCUboot semantic version byte encoding used by the local Zigbee SDK.
 * Release tooling rejects components >255 to prevent truncation. */
#define VIMAR_OTA_FILE_VERSION(major, minor, revision, build) \
    (((uint32_t)(major) << 24) | ((uint32_t)(minor) << 16) | \
     ((uint32_t)(revision) << 8) | (uint32_t)(build))
#endif
