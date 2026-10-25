/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_COMMON_RESTORE_H
#define VIMAR_COMMON_RESTORE_H
#include "loader_contract.h"
#define COMMON_RESTORE_MAX_FAMILIES 8u
#define COMMON_RESTORE_CHUNK_MAX 256u
#define COMMON_RESTORE_UNSET UINT32_MAX
enum common_restore_phase { COMMON_RESTORE_LOCKED,COMMON_RESTORE_TABLE,COMMON_RESTORE_READY,
 COMMON_RESTORE_WRITING,COMMON_RESTORE_PREPARED,COMMON_RESTORE_FINALIZING,COMMON_RESTORE_DONE,COMMON_RESTORE_FAILED };
/* Trusted platform callbacks, never request-provided pointers or address spans.
 * All callbacks return zero or negative status; positive results fail closed.
 * One serialized owner protects engine/reader/crypto/metadata for each call.
 * guard polls protection/cancellation; arm is explicit stock-maintenance OFF
 * authorization. Neither may write settings/NVS. erase is ONE aligned page;
 * write is ONE aligned word, allowing cancellation before the next NVMC action.
 * The adapter independently bounds those operations for its compiled role.
 */
struct common_restore_io {
 void *ctx;
 struct loader_contract_reader flash;
 struct loader_contract_hash hash;
 int (*live)(void *,struct loader_contract_live *);
 int (*guard)(void *);
 int (*arm)(void *);
 int (*erase)(void *,uint32_t,size_t);
 int (*write)(void *,uint32_t,const uint8_t *,size_t);
 int (*quiesce)(void *);
 int (*finalize)(void *,const uint8_t *,size_t); /* target implementation never returns */
 bool bootstrap; /* immutable build/platform purpose, not a wire field */
 int (*admit_bootstrap)(void *); /* real pinned-key embedded RESTORE verification */
 int (*request_loader)(void *); /* after scratch copy/readback, never normal MAIN reset */
};
struct common_restore {
 struct common_restore_io io;
 struct loader_contract_record records[COMMON_RESTORE_MAX_FAMILIES];
 size_t record_count;
 struct loader_restore_session session;
 _Alignas(4) uint8_t boot[LOADER_CONTRACT_LOADER_SIZE];
 _Alignas(4) uint8_t page[LOADER_CONTRACT_PAGE_SIZE];
 uint64_t owner;
 uint8_t measured_family[32],anchor_sha256[32];
 uint32_t reported_uid[2];
 uint32_t epoch,next_sequence,boot_mask,page_address,page_offset,table_offset;
 enum common_restore_phase phase;
};
/* Fresh state must be zero-initialized. owner and unpredictable nonzero epoch
 * originate in the authenticated platform connection, never a phone request.
 * Read all admission inputs before clearing/publishing the large output state.
 * Only compiled finite COMMON_CODE44K_ANCHOR_V1 records are supported here.
 */
int common_restore_open(struct common_restore *,const struct common_restore_io *,
 const struct loader_contract_record *,size_t,uint64_t owner,uint32_t epoch);
int common_restore_table_chunk(struct common_restore *,uint64_t,uint32_t,uint32_t,uint32_t,const uint8_t *,size_t);
int common_restore_begin(struct common_restore *,uint64_t,uint32_t,uint32_t);
int common_restore_page_chunk(struct common_restore *,uint64_t,uint32_t,uint32_t,uint32_t,uint32_t,const uint8_t *,size_t);
int common_restore_page_commit(struct common_restore *,uint64_t,uint32_t,uint32_t,uint32_t);
int common_restore_prepare(struct common_restore *,uint64_t,uint32_t,uint32_t);
int common_restore_finalize_request(struct common_restore *,uint64_t,uint32_t,uint32_t);
/* Adapter worker only: explicit finalize intent, quiescence, complete recheck,
 * then SRAM-only finalizer. A successful request is not restoration success. */
int common_restore_finalize_execute(struct common_restore *,uint64_t,uint32_t);
void common_restore_cancel(struct common_restore *,uint64_t);
#endif
