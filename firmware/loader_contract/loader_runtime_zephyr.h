/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_LOADER_RUNTIME_ZEPHYR_H
#define VIMAR_LOADER_RUNTIME_ZEPHYR_H
#include "loader_pair.h"
/* Fixed local FICR/UICR and protected loader reader. No request-supplied
 * identity, approved record, hash provider, range or anchor pointer. */
int loader_runtime_zephyr_snapshot(struct loader_runtime_identity *);
/* Discover the actual authenticated RECOVERY2/profile2 ABI, independent of
 * its release version. No request-supplied recovery digest or trust policy. */
int loader_pair_authenticate_zephyr(uint8_t loader_full_sha256[32],struct ota_image_info *recovery);
/* expected recovery is the FULLFILE pair/journal hash, never the SMP hash.
 * loader output retains FULL48KiB journalV2 semantics after typed admission. */
int loader_pair_verify_zephyr(const uint8_t expected_recovery_file_sha256[32],uint8_t loader_full_sha256[32],
 struct ota_image_info *recovery);
#endif
