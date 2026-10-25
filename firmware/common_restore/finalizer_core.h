/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_COMMON_RESTORE_FINALIZER_CORE_H
#define VIMAR_COMMON_RESTORE_FINALIZER_CORE_H
#include "loader_contract.h"
#include "ram.h"
/* Target entry copies this vtable into SRAM and validates every target/source/
 * stack address before boot erasure. Every callback and reachable callee must
 * be SRAM-resident. No libraries, Flash literals or OS calls may be reachable.
 * erase/write callbacks poll protection while NVMC is busy, not just on return.
 */
struct common_restore_final_io {
 void *ctx;
 int (*guard)(void *);
 int (*erase_page)(void *,uint32_t);
 int (*write_word)(void *,uint32_t,uint32_t);
 int (*read_word)(void *,uint32_t,uint32_t *);
};
COMMON_RESTORE_RAM int common_restore_finalizer_core(const uint8_t *boot,size_t size,
 const struct common_restore_final_io *,volatile uint32_t *marker);
#endif
