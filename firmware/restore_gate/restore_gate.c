/* Opt-in nRF52840 gate. No changes to upstream MCUboot sources. */
#include <zephyr/kernel.h>
#include <bootutil/bootutil.h>
#include <bootutil/crypto/sha.h>
#include <bootutil/fault_injection_hardening.h>
#include <fprotect.h>
#include "restore_policy.h"
#include "restorer_hash.h"

_Static_assert(IMAGE_HASH_SIZE == 32, "Restorer allowlist requires SHA-256");

static bool authorized_boot;
fih_ret __real_boot_go(struct boot_rsp *rsp);
int __real_fprotect_area(uint32_t start, size_t length);

fih_ret __wrap_boot_go(struct boot_rsp *rsp)
{
 FIH_DECLARE(rc, FIH_FAILURE);
 authorized_boot = false;
 FIH_CALL(__real_boot_go, rc, rsp);
 if (FIH_EQ(rc, FIH_SUCCESS) && rsp->br_flash_dev_id == 0 &&
     rsp->br_image_off == 0xb0000) {
  bootutil_sha_context context;
  uint8_t digest[32];
  int error = bootutil_sha_init(&context);
  if (!error) {
   error = bootutil_sha_update(&context, (const void *)0xb0000,
                              CONFIG_VIMAR_STOCK_RESTORER_SIZE);
   if (!error) error = bootutil_sha_finish(&context, digest);
   bootutil_sha_drop(&context);
  }
  if (!error) authorized_boot = vimar_restore_authorized(true,
    rsp->br_flash_dev_id, rsp->br_image_off, CONFIG_VIMAR_STOCK_RESTORER_SIZE,
    digest, authorized_restorer_hash);
 }
 FIH_RET(rc);
}

int __wrap_fprotect_area(uint32_t start, size_t length)
{
 /* Only MCUboot's exact region is exempted, and only after boot_go success.
  * Normal recovery, main applications and all hash/verification failures keep
  * their existing hardware protection. No retained request can grant access. */
 if (authorized_boot && start == 0 && length == 0xc000) return 0;
 return __real_fprotect_area(start, length);
}
