/* SPDX-License-Identifier: Apache-2.0
 * Portable opt-in loader/backup-anchor contract. No hardware, flash mutation,
 * signature-verification bypass, privileged boot selection or ACL operations.
 */
#include "loader_contract.h"
#include <errno.h>
#include <string.h>

static uint16_t le16(const uint8_t *p) { return p[0] | (uint16_t)p[1] << 8; }
static uint32_t le32(const uint8_t *p) { return le16(p) | (uint32_t)le16(p + 2) << 16; }
static void put16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static void put32(uint8_t *p, uint32_t v) { put16(p, (uint16_t)v); put16(p + 2, (uint16_t)(v >> 16)); }
static int result(int rc) { return rc > 0 ? -EIO : rc; }
static bool all_ff(const uint8_t *p, size_t n)
{
 for (size_t i = 0; i < n; ++i) if (p[i] != 0xff) return false;
 return true;
}
static uint32_t crc32_ieee(const uint8_t *p, size_t n)
{
 uint32_t crc = UINT32_MAX;
 for (size_t i = 0; i < n; ++i) {
  crc ^= p[i];
  for (unsigned bit = 0; bit < 8; ++bit)
   crc = (crc >> 1) ^ (UINT32_C(0xedb88320) & (0u - (crc & 1u)));
 }
 return crc ^ UINT32_MAX;
}
static bool variant_valid(uint32_t variant) { return variant && variant != UINT32_MAX; }
static bool live_valid(const struct loader_contract_live *live)
{
 return live && live->part == LOADER_CONTRACT_PART && variant_valid(live->variant) &&
  live->flash_size == LOADER_CONTRACT_FLASH_SIZE && live->page_size == LOADER_CONTRACT_PAGE_SIZE &&
  live->ram_size == LOADER_CONTRACT_RAM_SIZE && live->uicr_size == LOADER_CONTRACT_UICR_SIZE;
}
static int decode_header(const uint8_t h[256], const struct loader_contract_live *live,
                         struct loader_anchor *anchor)
{
 static const uint8_t model[12] = {'V','I','M','A','R','3','0','8','0','5',0,0};
 if (memcmp(h, "VAR1", 4) || le16(h + 4) != 1 || le16(h + 6) != 256 ||
     le32(h + 8) != 1 || le32(h + 12) != 2 || le32(h + 16) != LOADER_CONTRACT_PART ||
     le32(h + 32) != LOADER_CONTRACT_FLASH_SIZE || le32(h + 36) != LOADER_CONTRACT_PAGE_SIZE ||
     le32(h + 40) != LOADER_CONTRACT_RAM_SIZE || le32(h + 44) != LOADER_CONTRACT_UICR_SIZE ||
     le32(h + 48) != LOADER_CONTRACT_TABLE_SIZE || memcmp(h + 52, model, sizeof(model)) ||
     !all_ff(h + 160, 88) || le32(h + 252) != LOADER_CONTRACT_COMMIT ||
     le32(h + 248) != crc32_ieee(h, 248)) return -EBADMSG;
 if (!live_valid(live) || le32(h + 20) != live->variant ||
     le32(h + 24) != live->uid[0] || le32(h + 28) != live->uid[1] ||
     memcmp(h + 96, live->uicr_sha256, 32)) return -EACCES;
 memset(anchor, 0, sizeof(*anchor));
 anchor->variant = le32(h + 20);
 anchor->uid[0] = le32(h + 24); anchor->uid[1] = le32(h + 28);
 memcpy(anchor->flash_sha256, h + 64, 32);
 memcpy(anchor->uicr_sha256, h + 96, 32);
 memcpy(anchor->table_sha256, h + 128, 32);
 return 0;
}
int loader_anchor_encode(uint8_t *page, size_t size, const struct loader_anchor *anchor)
{
 if (!page || size != LOADER_CONTRACT_ANCHOR_SIZE || !anchor || !variant_valid(anchor->variant))
  return -EINVAL;
 /* Support an anchor whose source struct is inside the destination buffer. */
 struct loader_anchor input = *anchor;
 memset(page, 0xff, size);
 memcpy(page, "VAR1", 4); put16(page + 4, 1); put16(page + 6, 256);
 put32(page + 8, 1); put32(page + 12, 2); put32(page + 16, LOADER_CONTRACT_PART);
 put32(page + 20, input.variant); put32(page + 24, input.uid[0]); put32(page + 28, input.uid[1]);
 put32(page + 32, LOADER_CONTRACT_FLASH_SIZE); put32(page + 36, LOADER_CONTRACT_PAGE_SIZE);
 put32(page + 40, LOADER_CONTRACT_RAM_SIZE); put32(page + 44, LOADER_CONTRACT_UICR_SIZE);
 put32(page + 48, LOADER_CONTRACT_TABLE_SIZE); memcpy(page + 52, "VIMAR30805\0", 12);
 memcpy(page + 64, input.flash_sha256, 32); memcpy(page + 96, input.uicr_sha256, 32);
 memcpy(page + 128, input.table_sha256, 32); put32(page + 248, crc32_ieee(page, 248));
 put32(page + 252, LOADER_CONTRACT_COMMIT);
 return 0;
}
int loader_anchor_decode(const uint8_t *page, size_t size,
                          const struct loader_contract_live *live, struct loader_anchor *out)
{
 if (!out) return -EINVAL;
 struct loader_anchor decoded;
 int rc = -EINVAL;
 if (page && size == LOADER_CONTRACT_ANCHOR_SIZE && live) {
  rc = all_ff(page + 256, size - 256) ? decode_header(page, live, &decoded) : -EBADMSG;
 }
 /* out may overlap page or live, including live's trusted UICR hash. Never
  * clear or publish it until every validation read has finished. */
 if (rc) memset(out, 0, sizeof(*out));
 else memcpy(out, &decoded, sizeof(decoded));
 return rc;
}
static bool hash_valid(const struct loader_contract_hash *hash)
{
 return hash && hash->begin && hash->update && hash->finish && hash->abort;
}
static int read_bytes(const struct loader_contract_reader *r, uint32_t offset, uint8_t *p, size_t n)
{
 if (!r || !r->read || offset > r->size || n > r->size - offset) return -EINVAL;
 return result(r->read(r->ctx, offset, p, n));
}
static int hash_stream(const struct loader_contract_reader *r, size_t size,
                        const uint8_t *prefix, size_t prefix_size,
                        const struct loader_contract_hash *hash, uint8_t out[32])
{
 if (!out) return -EINVAL;
 if (!r || !r->read || size > r->size || size > UINT32_MAX || !hash_valid(hash)) {
  memset(out, 0, 32);
  return -EINVAL;
 }
 uint8_t chunk[256], digest[32];
 int rc = result(hash->begin(hash->ctx));
 if (!rc && prefix_size) rc = result(hash->update(hash->ctx, prefix, prefix_size));
 for (uint32_t off = 0; !rc && off < size;) {
  size_t n = size - off < sizeof(chunk) ? size - off : sizeof(chunk);
  rc = read_bytes(r, off, chunk, n);
  if (!rc) rc = result(hash->update(hash->ctx, chunk, n));
  off += (uint32_t)n;
 }
 if (!rc) rc = result(hash->finish(hash->ctx, digest));
 hash->abort(hash->ctx);
 if (rc) memset(out, 0, 32);
 else memcpy(out, digest, 32);
 return rc;
}
int loader_contract_full_digest(const struct loader_contract_reader *r,
                                const struct loader_contract_hash *hash, uint8_t out[32])
{
 return hash_stream(r, LOADER_CONTRACT_LOADER_SIZE, NULL, 0, hash, out);
}
int loader_contract_family_digest(const struct loader_contract_reader *r,
                                  const struct loader_contract_hash *hash, uint8_t out[32])
{
 static const uint8_t domain[] = LOADER_CONTRACT_FAMILY_DOMAIN;
 return hash_stream(r, LOADER_CONTRACT_CODE_SIZE, domain, sizeof(domain), hash, out);
}
static int read_anchor(const struct loader_contract_reader *r,
                       const struct loader_contract_live *live, struct loader_anchor *out)
{
 uint8_t header[256], chunk[256];
 int rc = read_bytes(r, LOADER_CONTRACT_ANCHOR_OFFSET, header, sizeof(header));
 if (rc) return rc;
 struct loader_anchor decoded;
 rc = decode_header(header, live, &decoded);
 if (rc) return rc;
 for (uint32_t off = 256; off < LOADER_CONTRACT_ANCHOR_SIZE; off += sizeof(chunk)) {
  rc = read_bytes(r, LOADER_CONTRACT_ANCHOR_OFFSET + off, chunk, sizeof(chunk));
  if (rc) return rc;
  if (!all_ff(chunk, sizeof(chunk))) return -EBADMSG;
 }
 *out = decoded;
 return 0;
}
static int authorize_inputs(const struct loader_contract_reader *r,
 const struct loader_contract_record *records, size_t count, const struct loader_contract_live *live,
 const struct loader_contract_hash *hash, struct loader_contract_authorization *out)
{
 if (!r || !r->read || r->size < LOADER_CONTRACT_LOADER_SIZE || !records ||
     !count || count > LOADER_CONTRACT_MAX_RECORDS || !hash_valid(hash) || !live) return -EINVAL;
 bool legacy = false, common = false;
 for (size_t i = 0; i < count; ++i) {
  if (records[i].kind == LOADER_CONTRACT_LEGACY_FULL48K_SHA256) legacy = true;
  else if (records[i].kind == LOADER_CONTRACT_COMMON_CODE44K_ANCHOR_V1) common = true;
  else return -EINVAL;
 }
 uint8_t digest[32];
 int rc;
 if (legacy) {
  rc = loader_contract_full_digest(r, hash, digest);
  if (rc) return rc;
  for (size_t i = 0; i < count; ++i) {
   if (records[i].kind == LOADER_CONTRACT_LEGACY_FULL48K_SHA256 && !memcmp(digest, records[i].digest, 32)) {
    out->kind = LOADER_CONTRACT_LEGACY_FULL48K_SHA256;
    memcpy(out->measured_digest, digest, 32);
    return 0;
   }
  }
 }
 if (!common) return -EACCES;
 rc = loader_contract_family_digest(r, hash, digest);
 if (rc) return rc;
 bool found = false;
 for (size_t i = 0; i < count; ++i)
  if (records[i].kind == LOADER_CONTRACT_COMMON_CODE44K_ANCHOR_V1 && !memcmp(digest, records[i].digest, 32))
   found = true;
 if (!found) return -EACCES;
 struct loader_anchor anchor;
 rc = read_anchor(r, live, &anchor);
 if (rc) return rc;
 out->kind = LOADER_CONTRACT_COMMON_CODE44K_ANCHOR_V1;
 memcpy(out->measured_digest, digest, 32); out->anchor = anchor;
 return 0;
}
int loader_contract_authorize(const struct loader_contract_reader *r,
 const struct loader_contract_record *records, size_t count, const struct loader_contract_live *live,
 const struct loader_contract_hash *hash, struct loader_contract_authorization *out)
{
 if (!out) return -EINVAL;
 struct loader_contract_authorization authorized = {0};
 int rc = authorize_inputs(r, records, count, live, hash, &authorized);
 /* Reader storage, records and live expectations may all alias out. The
  * private result prevents eager zeroing from changing admission inputs. */
 if (rc) memset(out, 0, sizeof(*out));
 else memcpy(out, &authorized, sizeof(authorized));
 return rc;
}
struct buffer_reader { const uint8_t *bytes; };
static int read_buffer(void *ctx, uint32_t offset, uint8_t *p, size_t n)
{
 const struct buffer_reader *buffer = ctx;
 memcpy(p, buffer->bytes + offset, n);
 return 0;
}
static int hash_buffer(const uint8_t *p, size_t n, const struct loader_contract_hash *hash, uint8_t out[32])
{
 const struct buffer_reader buffer = {.bytes = p};
 const struct loader_contract_reader reader = {.ctx = (void *)&buffer, .size = n, .read = read_buffer};
 return hash_stream(&reader, n, NULL, 0, hash, out);
}
void loader_restore_session_reset(struct loader_restore_session *session)
{
 if (session) memset(session, 0, sizeof(*session));
}
int loader_restore_session_init(struct loader_restore_session *session, const struct loader_anchor *anchor)
{
 if (!session) return -EINVAL;
 if (!anchor || !variant_valid(anchor->variant)) {
  loader_restore_session_reset(session);
  return -EINVAL;
 }
 struct loader_anchor input = *anchor;
 loader_restore_session_reset(session);
 session->anchor = input; session->initialized = true;
 return 0;
}
int loader_restore_table_accept(struct loader_restore_session *session, const uint8_t *table,
                                size_t size, const struct loader_contract_hash *hash)
{
 if (!session || !session->initialized) return -EINVAL;
 if (session->writing) return -EBUSY;
 session->accepted = false;
 if (!table || size != LOADER_CONTRACT_TABLE_SIZE || !hash_valid(hash)) {
  memset(session->table, 0, sizeof(session->table));
  return -EINVAL;
 }
 /* Own the bytes before hashing, preventing caller-buffer mutation after
  * acceptance from changing the table used by page authorization. */
 memmove(session->table, table, size);
 uint8_t digest[32];
 int rc = hash_buffer(session->table, size, hash, digest);
 if (!rc && memcmp(digest, session->anchor.table_sha256, 32)) rc = -EACCES;
 /* This exact scratch geometry is the existing stock-restorer contract. */
 uint8_t erased[256]; memset(erased, 0xff, sizeof(erased));
 if (!rc) {
  rc = result(hash->begin(hash->ctx));
  for (size_t n = 0; !rc && n < LOADER_CONTRACT_PAGE_SIZE; n += sizeof(erased))
   rc = result(hash->update(hash->ctx, erased, sizeof(erased)));
  if (!rc) rc = result(hash->finish(hash->ctx, digest));
  hash->abort(hash->ctx);
 }
 if (!rc) {
  for (uint32_t address = LOADER_CONTRACT_SCRATCH_START; address < LOADER_CONTRACT_SCRATCH_END;
       address += LOADER_CONTRACT_PAGE_SIZE) {
   if (memcmp(session->table + (address / LOADER_CONTRACT_PAGE_SIZE) * 32, digest, 32)) {
    rc = -ENOTSUP; break;
   }
  }
 }
 if (rc) memset(session->table, 0, sizeof(session->table));
 else session->accepted = true;
 return rc;
}
int loader_restore_begin_write(struct loader_restore_session *session)
{
 if (!session || !session->initialized || !session->accepted) return -EACCES;
 session->writing = true;
 return 0;
}
int loader_restore_page_matches(const struct loader_restore_session *session, uint32_t address,
                                const uint8_t *page, size_t size, const struct loader_contract_hash *hash)
{
 if (!session || !session->initialized || !session->accepted) return -EACCES;
 if (!page || size != LOADER_CONTRACT_PAGE_SIZE || address >= LOADER_CONTRACT_FLASH_SIZE ||
     address % LOADER_CONTRACT_PAGE_SIZE ||
     (address >= LOADER_CONTRACT_SCRATCH_START && address < LOADER_CONTRACT_SCRATCH_END)) return -EINVAL;
 uint8_t digest[32];
 int rc = hash_buffer(page, size, hash, digest);
 if (!rc && memcmp(digest, session->table + (address / LOADER_CONTRACT_PAGE_SIZE) * 32, 32)) rc = -EACCES;
 return rc;
}
