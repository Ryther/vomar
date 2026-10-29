/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_LOADER_PAIR_H
#define VIMAR_LOADER_PAIR_H
#include "loader_runtime.h"
#include "../ota/ota_image.h"
struct loader_pair_result {
 struct loader_runtime_identity loader;
 /* JournalV2 consistency binding stays FULL48KiB, including the per-unit
  * anchor. It is never silently reinterpreted as a code-family digest. */
 uint8_t loader_full_sha256[32];
 struct ota_image_info recovery;
};
/* Version-independent admission of the signed RECOVERY2/profile2 update ABI.
 * Still authenticates the approved loader/anchor, key, role, model/profile,
 * image bounds and slot vectors. Publishes the ACTUAL file/signed-region hashes.
 * This is discovery/admission only; an active journal must use verify below. */
int loader_pair_authenticate(const struct loader_contract_reader *,
 const struct loader_contract_record *,size_t,const struct loader_contract_live *,
 const struct loader_contract_hash *,const uint8_t *recovery_image,size_t capacity,
 struct loader_pair_result *);
/* Explicit typed authority + pinned-key signed RECOVERY2/profile2 in slot1.
 * expected_recovery_file_sha256 is the FULL signed-file digest (pair binding).
 * recovery.signed_digest separately supplies the SMP/manifest identity hash.
 * Output may overlap inputs; every validation read precedes publication. */
int loader_pair_verify(const struct loader_contract_reader *,
 const struct loader_contract_record *,size_t,const struct loader_contract_live *,
 const struct loader_contract_hash *,const uint8_t *recovery_image,size_t capacity,
 const uint8_t expected_recovery_file_sha256[32],struct loader_pair_result *);
#endif
