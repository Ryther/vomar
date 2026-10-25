/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_OTA_RUNTIME_CONTRACT_H
#define VIMAR_OTA_RUNTIME_CONTRACT_H
#include <stdbool.h>
#include <stdint.h>
#define OTA_RUNTIME_CONTRACT_BINARY_SIZE 43u
#define OTA_RUNTIME_CONTRACT_TEXT_SIZE 61u
#define OTA_RUNTIME_CONTRACT_ZCL_SIZE (OTA_RUNTIME_CONTRACT_BINARY_SIZE+1u)
/* ZCL OCTET_STRING: length43 followed by43-byte binary v1.
 * Converter emits "v1:" + canonical unpadded base64url,61 ASCII bytes.
 * No flash, settings, radio, boot request or output operation. */
int ota_runtime_contract_encode(uint32_t sample,uint32_t boot,bool ready,
    const uint8_t recovery_digest[32],uint8_t out[OTA_RUNTIME_CONTRACT_ZCL_SIZE]);
#endif
