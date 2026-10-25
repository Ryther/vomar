/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_COMMON_RESTORE_RADIO_IDENTITY_H
#define VIMAR_COMMON_RESTORE_RADIO_IDENTITY_H
#include "loader_contract.h"
/* Address bytes are Bluetooth little endian. A secure fresh16-byte boot nonce
 * separates volatile pairing keys after reset, UID/role separate helpers.
 * Address is discovery metadata, not device/firmware authorization. */
int common_restore_radio_address(const uint32_t uid[2],const uint8_t nonce[16],unsigned role,
 const struct loader_contract_hash *,uint8_t out[6]);
#endif
