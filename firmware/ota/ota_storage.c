#if defined(CONFIG_VIMAR_P031_PROTECTION)
#include "boot_trace.h"
#include "vimar_power_protection.h"
#endif
#include "ota_storage.h"
#include "ota_format.h"
#include "ota_image.h"
#include <errno.h>
#include <string.h>
#include <zephyr/settings/settings.h>
#include <zephyr/retention/bootmode.h>
#include <zephyr/sys/reboot.h>

int ota_storage_load(struct ota_transaction *tx)
{
 uint8_t record[OTA_TRANSACTION_MAX_RECORD_SIZE];
 ssize_t n=settings_load_one("vimar/ota",record,sizeof(record));
 if(n<0)return (int)n;
 return ota_transaction_decode(record,(size_t)n,tx)?-EINVAL:0;
}
int ota_storage_save(const struct ota_transaction *tx)
{
 uint8_t record[OTA_TRANSACTION_MAX_RECORD_SIZE];
 size_t n=ota_transaction_record_size(tx);
 if(ota_transaction_encode(tx,record,n))return-EINVAL;
 return settings_save_one("vimar/ota",record,n);
}
int ota_storage_clear(void){return settings_delete("vimar/ota");}
int ota_storage_boot_route(void)
{
 struct ota_transaction tx;
 int loaded=ota_storage_load(&tx);
 if(loaded==-ENOENT||loaded==-EINVAL)return 0;
 if(loaded)return loaded;
 uint32_t region=0,total=0;uint8_t hash[32]={0};
 bool valid=ota_primary_extent((const uint8_t*)0xc000,0xa4000,&region,&total)==0;
 if(valid && ota_image_sha256((const uint8_t*)0xc000,region,hash))valid=false;
 enum ota_boot_action action=ota_transaction_boot(&tx,hash,valid);
 if(action==OTA_BOOT_CLEAR_COMPLETED)return ota_storage_clear();
 if(action==OTA_BOOT_ENTER_RECOVERY){
  int err=bootmode_set(BOOT_MODE_TYPE_BOOTLOADER);
  if(err)return err;
#if defined(CONFIG_VIMAR_P031_PROTECTION)
        (void)vimar_boot_trace_request(BOOT_REASON_OTA_INSTALL);
        int protection_rc=vimar_power_protection_flush();
        if(protection_rc)return protection_rc;
#endif
  sys_reboot(SYS_REBOOT_COLD);
  return-EIO;
 }
 return 0;
}
