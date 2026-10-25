/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_LOADER_RUNTIME_H
#define VIMAR_LOADER_RUNTIME_H
#include "loader_contract.h"
#define LOADER_RUNTIME_IDENTITY_PROTOCOL 2u
#define LOADER_RUNTIME_IDENTITY_COMMAND 1u
#define LOADER_RUNTIME_LEGACY_KIND "legacy-full48k-sha256"
#define LOADER_RUNTIME_COMMON_KIND "common-code44k-anchor-v1"
/* Portable opt-in source only: no READ handler/consumer is registered here.
 * digest uses the explicitly authorized kind; anchor_sha256 is a private
 * measurement of the validated4096-byte page, not attestation/signature. */
struct loader_runtime_identity {
 uint32_t uid[2];
 enum loader_contract_kind kind;
 uint8_t digest[32],anchor_sha256[32];
};
/* Caller supplies local hardware identity/UICR measurement and an immutable
 * exact48KiB reader plus compiled/signed approved typed records. Outputs may
 * overlap consumed inputs; no early clearing or publication is permitted. */
int loader_runtime_snapshot(const struct loader_contract_reader *,
 const struct loader_contract_record *,size_t,const struct loader_contract_live *,
 const struct loader_contract_hash *,struct loader_runtime_identity *);
#endif
