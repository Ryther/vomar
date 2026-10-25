/* SPDX-License-Identifier: Apache-2.0 */
#include "loader_contract.h"
#if __has_include("loader_restore_complete.h")
#include "loader_restore_complete.h"
#define HAS_COMPLETE 1
#endif
#include <errno.h>
#include <openssl/evp.h>
#include <string.h>
static EVP_MD_CTX *crypto;
static unsigned steps, fail_step, aborts, begins, reads, forbidden_reads;
static unsigned visits[256];
static uint32_t mutate_second = UINT32_MAX;
static int crypto_error, read_error;
static uint32_t fail_offset;
static int step(void) { return ++steps == fail_step ? crypto_error : 0; }
static int begin(void *ctx) {
 (void)ctx; ++begins; int rc = step(); if (rc) return rc;
 crypto = EVP_MD_CTX_new();
 return crypto && EVP_DigestInit_ex(crypto, EVP_sha256(), NULL) == 1 ? 0 : -EIO;
}
static int update(void *ctx, const uint8_t *p, size_t n) {
 (void)ctx; int rc = step(); if (rc) return rc;
 return EVP_DigestUpdate(crypto, p, n) == 1 ? 0 : -EIO;
}
static int finish(void *ctx, uint8_t out[32]) {
 (void)ctx; unsigned n; int rc = step(); if (rc) return rc;
 return EVP_DigestFinal_ex(crypto, out, &n) == 1 && n == 32 ? 0 : -EIO;
}
static void abort_hash(void *ctx) { (void)ctx; ++aborts; EVP_MD_CTX_free(crypto); crypto = NULL; }
static const struct loader_contract_hash hash = {NULL, begin, update, finish, abort_hash};
struct memory { const uint8_t *p; size_t size; };
static int read_memory(void *ctx, uint32_t off, uint8_t *p, size_t n) {
 struct memory *m = ctx; ++reads;
 if (off < 0xc000 || (off < 0xef000 && off + n > 0xb0000) ||
     off > m->size || n > m->size - off || n > 4096) { ++forbidden_reads; return -EINVAL; }
 if (read_error && off <= fail_offset && fail_offset - off < n) return read_error;
 memcpy(p, m->p + off, n);
 if (++visits[off / 4096] > 1 && off <= mutate_second && mutate_second - off < n)
  p[mutate_second - off] ^= 1;
 return 0;
}
void complete_inject(unsigned fail, int crypto_rc, uint32_t offset, int read_rc) {
 steps = aborts = begins = reads = forbidden_reads = 0; memset(visits, 0, sizeof(visits));
 mutate_second = UINT32_MAX;
 fail_step = fail; crypto_error = crypto_rc; fail_offset = offset; read_error = read_rc;
}
unsigned complete_steps(void) { return steps; }
unsigned complete_aborts(void) { return aborts; }
unsigned complete_begins(void) { return begins; }
void complete_mutate_second(uint32_t address) { mutate_second = address; }
unsigned complete_reads(void) { return reads; }
unsigned complete_forbidden(void) { return forbidden_reads; }
int complete_prepare(struct loader_restore_session *s, const struct loader_anchor *a, const uint8_t *table) {
 int rc = loader_restore_session_init(s, a);
 if (!rc) rc = loader_restore_table_accept(s, table, 8192, &hash);
 if (!rc) rc = loader_restore_begin_write(s);
 return rc;
}
int complete_verify(const struct loader_restore_session *s, const uint8_t *boot, size_t size,
 uint32_t mask, const uint8_t *flash, size_t flash_size, unsigned missing) {
 struct memory m = {flash, flash_size};
 struct loader_contract_reader reader = {&m, flash_size, read_memory};
 struct loader_contract_hash h = hash;
 if (missing == 1) h.begin = NULL;
 if (missing == 2) h.update = NULL;
 if (missing == 3) h.finish = NULL;
 if (missing == 4) h.abort = NULL;
 if (missing == 5) reader.read = NULL;
#ifdef HAS_COMPLETE
 return loader_restore_complete_verify(s, boot, size, mask, &reader, &h);
#else
 (void)s; (void)boot; (void)size; (void)mask; (void)reader; (void)h;
 return -ENOSYS;
#endif
}
