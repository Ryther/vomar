/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_LOADER_CONTRACT_H
#define VIMAR_LOADER_CONTRACT_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define LOADER_CONTRACT_CODE_SIZE 0xb000u
#define LOADER_CONTRACT_ANCHOR_OFFSET 0xb000u
#define LOADER_CONTRACT_ANCHOR_SIZE 0x1000u
#define LOADER_CONTRACT_ANCHOR_HEADER_SIZE 256u
#define LOADER_CONTRACT_LOADER_SIZE 0xc000u
#define LOADER_CONTRACT_FLASH_SIZE 0x100000u
#define LOADER_CONTRACT_PAGE_SIZE 0x1000u
#define LOADER_CONTRACT_RAM_SIZE 0x40000u
#define LOADER_CONTRACT_UICR_SIZE 0x1000u
#define LOADER_CONTRACT_TABLE_SIZE 0x2000u
#define LOADER_CONTRACT_PART 0x52840u
#define LOADER_CONTRACT_COMMIT 0xa60c17edu
#define LOADER_CONTRACT_SCRATCH_START 0xb0000u
#define LOADER_CONTRACT_SCRATCH_END 0xef000u
#define LOADER_CONTRACT_MAX_RECORDS 64u
/* sizeof includes exactly one trailing NUL. No caller-selected digest masks. */
#define LOADER_CONTRACT_FAMILY_DOMAIN "VIMAR30805-LOADER-CODE44K-ANCHOR1"

struct loader_contract_live {
 uint32_t part, variant, uid[2];
 uint32_t flash_size, page_size, ram_size, uicr_size;
 uint8_t uicr_sha256[32];
};
struct loader_anchor {
 uint32_t variant, uid[2];
 uint8_t flash_sha256[32], uicr_sha256[32], table_sha256[32];
};
struct loader_contract_reader {
 /* Caller keeps these bytes immutable throughout one complete operation. */
 void *ctx;
 size_t size;
 int (*read)(void *ctx, uint32_t offset, uint8_t *data, size_t size);
};
/* Caller owns and serializes crypto state. All operations return zero or a
 * negative error; positive results are rejected. abort releases/reset state
 * after every begin attempt, including failed begin and successful finish. */
struct loader_contract_hash {
 void *ctx;
 int (*begin)(void *ctx);
 int (*update)(void *ctx, const uint8_t *data, size_t size);
 int (*finish)(void *ctx, uint8_t digest[32]);
 void (*abort)(void *ctx);
};
enum loader_contract_kind {
 LOADER_CONTRACT_LEGACY_FULL48K_SHA256 = 1,
 LOADER_CONTRACT_COMMON_CODE44K_ANCHOR_V1 = 2,
};
struct loader_contract_record {
 enum loader_contract_kind kind;
 uint8_t digest[32];
};
struct loader_contract_authorization {
 enum loader_contract_kind kind;
 uint8_t measured_digest[32];
 struct loader_anchor anchor; /* Zero for an exact legacy full-hash match. */
};
/* Encode a complete canonical RAM page. A future SWD writer MUST program and
 * verify the body first, then program the commit word at offset252 last.
 * This codec performs no flash IO and grants no programming authority. */
int loader_anchor_encode(uint8_t *page, size_t size, const struct loader_anchor *anchor);
/* Live identity/geometry and UICR digest must come from local hardware reads.
 * Successful decoding alone never grants a loader-protection exception.
 * Outputs may overlap inputs: publication/zeroing follows all validation reads. */
int loader_anchor_decode(const uint8_t *page, size_t size,
 const struct loader_contract_live *live, struct loader_anchor *out);
int loader_contract_full_digest(const struct loader_contract_reader *,
 const struct loader_contract_hash *, uint8_t digest[32]);
int loader_contract_family_digest(const struct loader_contract_reader *,
 const struct loader_contract_hash *, uint8_t digest[32]);
int loader_contract_authorize(const struct loader_contract_reader *,
 const struct loader_contract_record *, size_t count, const struct loader_contract_live *,
 const struct loader_contract_hash *, struct loader_contract_authorization *out);

/* Explicit opt-in portable RAM state only. No writer/eraser/reset callbacks.
 * Callers serialize the entire session and treat its RAM as private trusted
 * state. Only initialize it from a successfully decoded/authorized anchor. */
struct loader_restore_session {
 struct loader_anchor anchor;
 uint8_t table[LOADER_CONTRACT_TABLE_SIZE];
 bool initialized, accepted, writing;
};
int loader_restore_session_init(struct loader_restore_session *, const struct loader_anchor *);
void loader_restore_session_reset(struct loader_restore_session *);
int loader_restore_table_accept(struct loader_restore_session *, const uint8_t *table,
 size_t size, const struct loader_contract_hash *);
int loader_restore_begin_write(struct loader_restore_session *);
int loader_restore_page_matches(const struct loader_restore_session *, uint32_t address,
 const uint8_t *page, size_t size, const struct loader_contract_hash *);
#endif
