/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_LOADER_RESTORE_COMPLETE_H
#define VIMAR_LOADER_RESTORE_COMPLETE_H
#include "loader_contract.h"

#define LOADER_RESTORE_COMPLETE_BOOT_MASK UINT32_C(0xfff)

/* Read-only final verification of the ORIGINAL logical 1 MiB FLASH image.
 * Requires a locally authorized anchor, accepted table frozen by begin_write,
 * and all twelve original boot pages staged contiguously in exactly 48 KiB.
 * The mask is caller-owned evidence of successful staging, not an attestation;
 * every staged boot page is independently checked against the anchored table.
 *
 * Logical bytes: [0,C000) from boot RAM; [B0000,EF000) synthetic FF; all other
 * bytes from actual_flash. The running helper in scratch need not be erased.
 * The reader must describe EXACTLY 1 MiB and return zero only after completely
 * filling each requested buffer. No reads target live boot or scratch.
 *
 * The caller holds one exclusive session/FLASH/boot/crypto lock throughout:
 * no writes, reset, table replacement, buffer alias mutation, interrupt writer,
 * or concurrent/reentrant hash use. Callbacks must honor the same rule and may
 * cancel by returning a negative error. Inputs and callback descriptors remain
 * immutable until return. This helper has no output buffer, performs no state
 * publication/mutation, and never authorizes an erase, finalizer, or reset.
 * Return zero ONLY for a matching logical full-image SHA256. A caller must
 * discard that result if any protected input changes before its next action.
 * Stack includes one 4096-byte page, anchor/digests, and callback/core frames;
 * actual target stack and resource fit require a later integration build.
 */
int loader_restore_complete_verify(const struct loader_restore_session *session,
 const uint8_t *boot, size_t boot_size, uint32_t boot_mask,
 const struct loader_contract_reader *actual_flash,
 const struct loader_contract_hash *hash);
#endif
