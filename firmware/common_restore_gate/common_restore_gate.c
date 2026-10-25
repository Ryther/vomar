/* SPDX-License-Identifier: Apache-2.0
 * Opt-in wrapper. Actual SDK boot_go owns the signature/selection result;
 * this module supplies only the additional common RESTORE admission policy.
 */
#include "common_restore_policy.h"
#include <bootutil/bootutil.h>
#include <bootutil/crypto/sha.h>
#include <bootutil/fault_injection_hardening.h>
#include <fprotect.h>
#include <hal/nrf_ficr.h>
#include <errno.h>

#if !defined(CONFIG_MCUBOOT) || !defined(CONFIG_SOC_NRF52840) || \
 !defined(CONFIG_BOOT_FIRMWARE_LOADER) || !defined(CONFIG_BOOT_VALIDATE_SLOT0) || \
 !defined(CONFIG_BOOT_SIGNATURE_TYPE_ECDSA_P256) || !defined(CONFIG_BOOT_USE_CC310) || \
 !defined(CONFIG_BOOT_USE_NRF_CC310_BL) || !defined(CONFIG_BOOT_FIH_PROFILE_OFF) || \
 !defined(CONFIG_FPROTECT) || !defined(CONFIG_MCUBOOT_USE_TLV_ALLOW_LIST)
#error "Common restore gate requires audited nRF52840 firmware-loader signature/configuration"
#endif
#if defined(CONFIG_BOOT_VALIDATE_SLOT0_ONCE) || defined(CONFIG_BOOT_BYPASS_KEY_MATCH) || \
 defined(CONFIG_NCS_MCUBOOT_LCS_AWARE) || defined(CONFIG_BOOT_SIGNATURE_TYPE_NONE) || \
 defined(CONFIG_VIMAR_STOCK_RESTORE_GATE) || defined(CONFIG_MCUBOOT_ACTION_HOOKS) || \
 defined(CONFIG_BOOT_IMAGE_ACCESS_HOOKS) || defined(CONFIG_BOOT_GO_HOOKS) || \
 defined(CONFIG_BOOT_FLASH_AREA_HOOKS) || defined(CONFIG_BOOT_ENCRYPT_IMAGE) || \
 defined(CONFIG_BOOT_HW_KEY) || defined(CONFIG_NCS_BOOT_SIGNATURE_USING_ITS) || \
 defined(CONFIG_BOOT_SIGNATURE_USING_KMU) || defined(CONFIG_BOOT_SWAP_USING_SCRATCH) || \
 defined(CONFIG_BOOT_SWAP_USING_MOVE) || defined(CONFIG_BOOT_SWAP_USING_OFFSET) || \
 defined(CONFIG_BOOT_UPGRADE_ONLY) || defined(CONFIG_MCUBOOT_COMPRESSED_IMAGE_SUPPORT_ENABLED)
#error "Common restore gate refuses unaudited bypass/hook/image/wrapper configuration"
#endif
_Static_assert(IMAGE_HASH_SIZE==32,"Common restore gate requires SHA256");
static bool authorized_boot;
fih_ret __real_boot_go(struct boot_rsp *rsp);
int __real_fprotect_area(uint32_t start,size_t length);
static int read_live(struct loader_contract_live *live)
{
 live->part=NRF_FICR->INFO.PART;live->variant=NRF_FICR->INFO.VARIANT;
 live->uid[0]=nrf_ficr_deviceid_get(NRF_FICR,0);live->uid[1]=nrf_ficr_deviceid_get(NRF_FICR,1);
 live->page_size=nrf_ficr_codepagesize_get(NRF_FICR);
 uint64_t flash=(uint64_t)live->page_size*nrf_ficr_codesize_get(NRF_FICR);
 uint64_t ram=(uint64_t)NRF_FICR->INFO.RAM*1024u;
 if(flash>UINT32_MAX||ram>UINT32_MAX)return-EOVERFLOW;
 live->flash_size=(uint32_t)flash;live->ram_size=(uint32_t)ram;
 live->uicr_size=LOADER_CONTRACT_UICR_SIZE;
 bootutil_sha_context context={0};
 int rc=bootutil_sha_init(&context);
 if(!rc)rc=bootutil_sha_update(&context,(const void*)0x10001000,LOADER_CONTRACT_UICR_SIZE);
 if(!rc)rc=bootutil_sha_finish(&context,live->uicr_sha256);
 bootutil_sha_drop(&context);
 return rc;
}
fih_ret __wrap_boot_go(struct boot_rsp *rsp)
{
 FIH_DECLARE(rc,FIH_FAILURE);
 authorized_boot=false;
 FIH_CALL(__real_boot_go,rc,rsp);
 if(FIH_EQ(rc,FIH_SUCCESS)&&rsp&&rsp->br_flash_dev_id==0&&rsp->br_image_off==COMMON_RESTORE_SLOT){
  struct loader_contract_live live={0};
  if(!read_live(&live))
   authorized_boot=common_restore_admit(true,rsp->br_flash_dev_id,rsp->br_image_off,
    (const uint8_t*)COMMON_RESTORE_SLOT,COMMON_RESTORE_LIMIT,
    (const uint8_t*)LOADER_CONTRACT_ANCHOR_OFFSET,LOADER_CONTRACT_ANCHOR_SIZE,&live)==0;
 }
 /* Additional admission failure never replaces the real SDK boot result.
  * Phase3 RESTORE code must revalidate anchor/live identity before any writes. */
 FIH_RET(rc);
}
int __wrap_fprotect_area(uint32_t start,size_t length)
{
 if(authorized_boot&&start==0&&length==LOADER_CONTRACT_LOADER_SIZE)return 0;
 return __real_fprotect_area(start,length);
}
