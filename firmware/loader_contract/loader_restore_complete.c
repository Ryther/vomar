/* SPDX-License-Identifier: Apache-2.0
 * Opt-in portable verification only. No flash IO mutation or consumer hooks.
 */
#include "loader_restore_complete.h"
#include <errno.h>
#include <string.h>

_Static_assert(LOADER_CONTRACT_LOADER_SIZE == 12u * LOADER_CONTRACT_PAGE_SIZE,
 "The completion contract requires exactly twelve original boot pages");
_Static_assert(LOADER_CONTRACT_FLASH_SIZE / LOADER_CONTRACT_PAGE_SIZE * 32u ==
 LOADER_CONTRACT_TABLE_SIZE, "The anchored table must cover all FLASH pages");

static int result(int rc) { return rc > 0 ? -EIO : rc; }
static int digest_bytes(const struct loader_contract_hash *hash,
 const uint8_t *bytes, size_t size, uint8_t digest[32])
{
 int rc = result(hash->begin(hash->ctx));
 if (!rc) rc = result(hash->update(hash->ctx, bytes, size));
 if (!rc) rc = result(hash->finish(hash->ctx, digest));
 hash->abort(hash->ctx);
 return rc;
}
static bool scratch(uint32_t address)
{
 return address >= LOADER_CONTRACT_SCRATCH_START && address < LOADER_CONTRACT_SCRATCH_END;
}
static int logical_page(const struct loader_contract_reader *reader, const uint8_t *boot,
 uint32_t address, uint8_t page[LOADER_CONTRACT_PAGE_SIZE])
{
 if (address < LOADER_CONTRACT_LOADER_SIZE) memcpy(page, boot + address, LOADER_CONTRACT_PAGE_SIZE);
 else if (scratch(address)) memset(page, 0xff, LOADER_CONTRACT_PAGE_SIZE);
 else {
  /* Constant geometry above still gets a local overflow-safe bounds check. */
  if (address > reader->size || LOADER_CONTRACT_PAGE_SIZE > reader->size - address) return -EINVAL;
  return result(reader->read(reader->ctx, address, page, LOADER_CONTRACT_PAGE_SIZE));
 }
 return 0;
}
int loader_restore_complete_verify(const struct loader_restore_session *session,
 const uint8_t *boot, size_t boot_size, uint32_t boot_mask,
 const struct loader_contract_reader *actual_flash, const struct loader_contract_hash *hash)
{
 if (!session || !session->initialized || !session->accepted || !session->writing) return -EACCES;
 if (!boot || boot_size != LOADER_CONTRACT_LOADER_SIZE || boot_mask != LOADER_RESTORE_COMPLETE_BOOT_MASK ||
     !actual_flash || !actual_flash->read || actual_flash->size != LOADER_CONTRACT_FLASH_SIZE ||
     !hash || !hash->begin || !hash->update || !hash->finish || !hash->abort) return -EINVAL;
 /* No caller-visible writes, including failure paths. Pin expected digests
  * before callbacks; caller's trusted RAM still requires external exclusion. */
 const struct loader_anchor anchor = session->anchor;
 uint8_t digest[32], page[LOADER_CONTRACT_PAGE_SIZE];
 int rc = digest_bytes(hash, session->table, sizeof(session->table), digest);
 if (rc) return rc;
 if (memcmp(digest, anchor.table_sha256, sizeof(digest))) return -EACCES;

 /* Do not rely solely on a stale accepted bit for original scratch geometry. */
 memset(page, 0xff, sizeof(page));
 rc = digest_bytes(hash, page, sizeof(page), digest);
 if (rc) return rc;
 for (uint32_t address = LOADER_CONTRACT_SCRATCH_START; address < LOADER_CONTRACT_SCRATCH_END;
      address += LOADER_CONTRACT_PAGE_SIZE)
  if (memcmp(session->table + address / LOADER_CONTRACT_PAGE_SIZE * 32u, digest, sizeof(digest))) return -EACCES;

 /* Recheck all 193 nonscratch logical pages, including all twelve RAM pages.
  * Session/table immutability is mandatory across this and the full stream. */
 for (uint32_t address = 0; address < LOADER_CONTRACT_FLASH_SIZE; address += LOADER_CONTRACT_PAGE_SIZE) {
  if (scratch(address)) continue;
  rc = logical_page(actual_flash, boot, address, page);
  if (!rc) rc = loader_restore_page_matches(session, address, page, sizeof(page), hash);
  if (rc) return rc;
 }

 rc = result(hash->begin(hash->ctx));
 for (uint32_t address = 0; !rc && address < LOADER_CONTRACT_FLASH_SIZE; address += LOADER_CONTRACT_PAGE_SIZE) {
  rc = logical_page(actual_flash, boot, address, page);
  if (!rc) rc = result(hash->update(hash->ctx, page, sizeof(page)));
 }
 if (!rc) rc = result(hash->finish(hash->ctx, digest));
 hash->abort(hash->ctx);
 if (!rc && memcmp(digest, anchor.flash_sha256, sizeof(digest))) rc = -EACCES;
 return rc;
}
