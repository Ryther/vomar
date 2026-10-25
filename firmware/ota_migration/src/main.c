/* Signed primary remains valid while recovery pages are copied/retried.
 * Never initializes output pins, consumes handoff marker, or changes loader. */
#include <zephyr/kernel.h>
#include <zephyr/drivers/flash.h>
#include <zephyr/retention/bootmode.h>
#include <zephyr/sys/reboot.h>
#include <zephyr/logging/log.h>
#include <hal/nrf_ficr.h>
#include <psa/crypto.h>
#include <errno.h>
#include <string.h>
#include "migration_copy.h"
#include "ota_image.h"
#include "recovery_blob.h"
#if defined(CONFIG_MIGRATION_LEGACY_ZIGBEE_ENTRY)
#include "legacy_bridge_entry_zephyr.h"
#endif
#if defined(CONFIG_VIMAR_LOADER_RUNTIME_V2)
#include "loader_runtime_zephyr.h"
#elif defined(CONFIG_MIGRATION_COMMON)
#include "common_platform.h"
#else
#include "target_uid.h"
#endif
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
#include "migration_policy.h"
#include "vimar_power_protection.h"
#include <zephyr/settings/settings.h>
#include <zephyr/drivers/retained_mem.h>
static const struct device *marker=DEVICE_DT_GET(DT_NODELABEL(gpregret2));
static int warm_load(void*c,uint8_t*p,size_t n){ARG_UNUSED(c);ssize_t r=settings_load_one("vimar/handoff",p,n);return r==(ssize_t)n?0:-EIO;}
static int warm_get(void*c,uint8_t*p){ARG_UNUSED(c);return retained_mem_read(marker,0,p,1);}
static int warm_set(void*c,uint8_t p){ARG_UNUSED(c);return retained_mem_write(marker,0,&p,1);}
static const struct research_handoff_io warm_io={.load=warm_load,.get_marker=warm_get,.set_marker=warm_set};
static int protected_preflight(const uint32_t uid[2],const uint8_t loader_digest[32]){
 int rc=settings_subsys_init();if(rc)return rc;
#if defined(CONFIG_MIGRATION_LEGACY_ZIGBEE_ENTRY)
 rc=legacy_bridge_prepare(uid,loader_digest,expected_recovery_sha256);if(rc)return rc;
#else
 ARG_UNUSED(uid);ARG_UNUSED(loader_digest);
#endif
 uint8_t old[176];ssize_t n=settings_load_one("vimar/ota",old,sizeof(old));
 rc=migration_protection_preflight((int)n,&warm_io);if(rc)return rc;
 return vimar_power_protection_init();
}
#endif
#if defined(CONFIG_MIGRATION_STAGE_PROBE)
#include <zephyr/settings/settings.h>
#include "ota_storage.h"
#include "probe_manifest.h"
#endif
LOG_MODULE_REGISTER(vimar_migration,LOG_LEVEL_INF);
static const struct device *flash_dev=DEVICE_DT_GET(DT_CHOSEN(zephyr_flash_controller));
static int read_uid(void *ctx,uint32_t uid[2]){ARG_UNUSED(ctx);uid[0]=nrf_ficr_deviceid_get(NRF_FICR,0);uid[1]=nrf_ficr_deviceid_get(NRF_FICR,1);return 0;}
static int digest(void *ctx,const uint8_t *p,size_t n,uint8_t out[32]){ARG_UNUSED(ctx);return ota_image_sha256(p,n,out);}
static int verify_image(void *ctx,const uint8_t *p,size_t n){
 ARG_UNUSED(ctx);struct ota_image_info info;
#if defined(CONFIG_MIGRATION_COMMON)
 int rc=ota_image_verify_primary_for_profile(p,n,2,&info);
 return rc?rc:migration_common_recovery_authorized(&info,n);
#else
 int rc=ota_image_verify_primary(p,n,&info);return rc?rc:(info.output_size==n?0:-EBADMSG);
#endif
}
static int read_flash(void *ctx,uint32_t addr,uint8_t *p,size_t n){ARG_UNUSED(ctx);return flash_read(flash_dev,addr,p,n);}
static int erase_flash(void *ctx,uint32_t addr,size_t n){ARG_UNUSED(ctx);return flash_erase(flash_dev,addr,n);}
static int write_flash(void *ctx,uint32_t addr,const uint8_t *p,size_t n){ARG_UNUSED(ctx);return flash_write(flash_dev,addr,p,n);}
static int verify_loader(uint8_t actual_digest[32])
{
#if defined(CONFIG_VIMAR_LOADER_RUNTIME_V2)
 if(actual_digest)return-ENOTSUP;
 struct loader_runtime_identity identity;
 return loader_runtime_zephyr_snapshot(&identity);
#else
 uint8_t buf[256],hash[32];size_t size=0;
 psa_hash_operation_t h=psa_hash_operation_init();
 if(psa_crypto_init()!=PSA_SUCCESS||psa_hash_setup(&h,PSA_ALG_SHA_256)!=PSA_SUCCESS)return-EIO;
 int rc=0;
 for(uint32_t addr=0;addr<0xc000&&!rc;addr+=sizeof(buf)){
  rc=flash_read(flash_dev,addr,buf,sizeof(buf));
  if(!rc&&psa_hash_update(&h,buf,sizeof(buf))!=PSA_SUCCESS)rc=-EIO;
 }
 if(!rc&&(psa_hash_finish(&h,hash,sizeof(hash),&size)!=PSA_SUCCESS||size!=32))rc=-EIO;
 psa_hash_abort(&h);
 if(rc)return rc;
 if(actual_digest)memcpy(actual_digest,hash,32);
#if defined(CONFIG_MIGRATION_COMMON)
 return migration_common_loader_authorized(hash,migration_allowed_loaders,MIGRATION_ALLOWED_LOADER_COUNT);
#else
 return memcmp(hash,expected_loader_sha256,32)?-EACCES:0;
#endif
#endif
}
int main(void)
{
 uint32_t uid[2];read_uid(NULL,uid);
#if defined(CONFIG_MIGRATION_COMMON)
 if(NRF_FICR->INFO.PART!=0x52840u){LOG_ERR("Unsupported MCU; stopped before any mutation");return 0;}
#else
 if(uid[0]!=MIGRATION_UID0||uid[1]!=MIGRATION_UID1){LOG_ERR("Wrong target; stopped before any mutation");return 0;}
#endif
 if(!device_is_ready(flash_dev)){LOG_ERR("Flash not ready");return 0;}
 uint8_t loader_digest[32]={0};
#if defined(CONFIG_MIGRATION_LEGACY_ZIGBEE_ENTRY)
 int rc=verify_loader(loader_digest);
#else
 int rc=verify_loader(NULL);
#endif
 if(rc){LOG_ERR("Loader authorization mismatch: %d",rc);return 0;}
#if defined(CONFIG_MIGRATION_COMMON)
 rc=verify_image(NULL,recovery_blob,RECOVERY_BLOB_SIZE);
 if(rc){LOG_ERR("Common recovery authorization mismatch: %d",rc);return 0;}
#endif
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
 rc=protected_preflight(uid,loader_digest);
 if(rc){LOG_ERR("Protected migration preflight rejected: %d",rc);
  if(!bootmode_set(BOOT_MODE_TYPE_BOOTLOADER))sys_reboot(SYS_REBOOT_COLD);
  return 0;
 }
#endif
 /* A reset while writing recovery must return to this valid primary. */
 rc=bootmode_clear();if(rc){LOG_ERR("Cannot clear boot request: %d",rc);return 0;}
 /* The common image binds this attempt to locally read identity. The copy
  * engine independently rereads those UID words before every copy/retry. */
#if defined(CONFIG_MIGRATION_COMMON)
 const struct migration_copy_bundle bundle={.uid={uid[0],uid[1]},.data=recovery_blob,.size=RECOVERY_BLOB_SIZE};
#else
 const struct migration_copy_bundle bundle={.uid={MIGRATION_UID0,MIGRATION_UID1},.data=recovery_blob,.size=RECOVERY_BLOB_SIZE};
#endif
 struct migration_copy_bundle checked=bundle;
#if defined(CONFIG_VIMAR_LOADER_RUNTIME_V2)
 /* The fixed embedded blob was already authenticated above. This full-file
  * consistency digest is not loader authority or the REC signed-region hash. */
 rc=ota_image_sha256(recovery_blob,RECOVERY_BLOB_SIZE,checked.sha256);
 if(rc){LOG_ERR("Recovery consistency digest unavailable: %d",rc);return 0;}
#else
 memcpy(checked.sha256,expected_recovery_sha256,32);
#endif
 const struct migration_copy_io io={.read_uid=read_uid,.sha256=digest,.verify_image=verify_image,.read=read_flash,.erase=erase_flash,.write=write_flash};
 for(;;){
  rc=migration_copy_run(&checked,&io);
  if(!rc)break;
  LOG_ERR("Recovery migration paused: %d; retaining valid primary",rc);k_sleep(K_SECONDS(2));
 }
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
 while(vimar_power_protection_flush()){LOG_ERR("Protection checkpoint unavailable; migration retains valid primary");k_sleep(K_SECONDS(1));}
#endif
 LOG_INF("Device recovery copied and verified; loader/identity unchanged");
#if defined(CONFIG_MIGRATION_STAGE_PROBE)
 rc=settings_subsys_init();
 if(!rc){struct ota_image_info info;rc=ota_image_authenticate((const uint8_t*)PROBE_STAGE_START,PROBE_CANDIDATE_SIZE,PROBE_STAGE_START-0xc000,&info);
  if(!rc){struct ota_transaction tx={.format_version=1,.generation=1,.state=OTA_TRANSACTION_PENDING,.stage_start=PROBE_STAGE_START,.stage_end=0xae000,.candidate_size=PROBE_CANDIDATE_SIZE,.signed_image_size=info.output_size};memcpy(tx.candidate_digest,info.source_digest,32);memcpy(tx.final_digest,info.signed_digest,32);rc=ota_storage_save(&tx);}
 }
 if(rc){LOG_ERR("Bench staged candidate rejected: %d",rc);return 0;}
#endif
#if defined(CONFIG_MIGRATION_LEGACY_ZIGBEE_ENTRY)
 rc=legacy_bridge_record_recovery_entry();
 if(rc){LOG_ERR("Permanent recovery entry checkpoint failed: %d",rc);return 0;}
#endif
 rc=bootmode_set(BOOT_MODE_TYPE_BOOTLOADER);
 if(rc){LOG_ERR("Recovery boot request failed: %d",rc);return 0;}
 sys_reboot(SYS_REBOOT_COLD);return 0;
}
