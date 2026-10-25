/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_COMMON_RESTORE_PROTOCOL_H
#define VIMAR_COMMON_RESTORE_PROTOCOL_H
#include "common_restore.h"
#define COMMON_RESTORE_PROTOCOL 2u
#define COMMON_RESTORE_WIRE_HEADER 24u
#define COMMON_RESTORE_WIRE_CHUNK 192u /*216-byte frame fits negotiated247 MTU */
#define COMMON_RESTORE_STATUS_SIZE 128u
/* Wire header little endian: version/op/reserved16, epoch32, sequence32,
 * page-address32, offset32, payload-length16, reserved16. The sole address
 * operation is an original page target checked by the engine, never a pointer.
 * owner is platform connection authority and is absent from this wire format.
 */
int common_restore_dispatch(struct common_restore *,uint64_t,const uint8_t *,size_t,const uint8_t *,size_t);
int common_restore_status(const struct common_restore *,unsigned role,unsigned protection_flags,
 unsigned last_op,uint32_t last_sequence,uint8_t *,size_t);
#endif
