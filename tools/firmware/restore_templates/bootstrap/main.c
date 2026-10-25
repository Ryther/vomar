/* Signed main-slot bridge: install the signed scratch restorer, then request it.
 * Candidate restricted to the exact Vimar identity from the backup. */
#include <string.h>
#include <zephyr/kernel.h>
#include <zephyr/drivers/flash.h>
#include <zephyr/retention/bootmode.h>
#include <zephyr/sys/reboot.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/crc.h>
#include <hal/nrf_ficr.h>
#include "restorer_blob.h"
LOG_MODULE_REGISTER(restore_bridge,LOG_LEVEL_INF);
int main(void) {
 if(NRF_FICR->INFO.PART!=0x52840 || NRF_FICR->INFO.VARIANT!=0x@VIMAR_CHIP_VARIANT@ || NRF_FICR->DEVICEID[0]!=0x@VIMAR_UID0@ || NRF_FICR->DEVICEID[1]!=0x@VIMAR_UID1@) {LOG_ERR("Refusing non-authorized target");return 0;}
 if(sizeof(restorer_blob)>0x3f000 || crc32_ieee(restorer_blob,sizeof(restorer_blob))!=RESTORER_CRC32) {LOG_ERR("Blob check failed");return 0;}
 const struct device *dev=DEVICE_DT_GET(DT_CHOSEN(zephyr_flash_controller));
 if(!device_is_ready(dev))return 0;
 LOG_INF("Installing signed scratch restorer size=%u",(unsigned)sizeof(restorer_blob));
 int error=flash_erase(dev,0xb0000,0x3f000);
 if(error==0)error=flash_write(dev,0xb0000,restorer_blob,sizeof(restorer_blob));
 if(error!=0 || memcmp((const void *)0xb0000,restorer_blob,sizeof(restorer_blob))!=0){LOG_ERR("Restorer install failed %d",error);return 0;}
 error=bootmode_set(BOOT_MODE_TYPE_BOOTLOADER);
 if(error){LOG_ERR("Cannot request scratch restorer %d",error);return 0;}
 LOG_INF("Signed scratch restorer installed, boot request set");
 sys_reboot(SYS_REBOOT_COLD);return 0;
}
