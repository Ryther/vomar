/* Device-bound Vimar restoration candidate. Physical validation pending. */
#include <errno.h>
#include <string.h>
#include <zephyr/kernel.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/drivers/flash.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/reboot.h>
#include <psa/crypto.h>
#include <hal/nrf_ficr.h>
#include "probe_manifest.h"
#include "restore_flasher.h"
LOG_MODULE_REGISTER(restore_probe,LOG_LEVEL_INF);
#define FLASH_SIZE 0x100000U
#define PAGE_SIZE 4096U
#define PAGE_UNSET 0xffffffffU
#define SVC_UUID BT_UUID_128_ENCODE(0xfde30805,0xc001,0x4a40,0x8d00,0x308050000010)
#define CMD_UUID BT_UUID_128_ENCODE(0xfde30805,0xc001,0x4a40,0x8d00,0x308050000011)
static struct bt_uuid_128 service_uuid=BT_UUID_INIT_128(SVC_UUID);
static struct bt_uuid_128 command_uuid=BT_UUID_INIT_128(CMD_UUID);
static const struct device *flash=DEVICE_DT_GET(DT_CHOSEN(zephyr_flash_controller));
static uint8_t page[PAGE_SIZE] __aligned(4);
static uint32_t boot[RESTORE_BOOT_SIZE/4] __aligned(4);
static uint8_t reply[20];
static uint32_t page_address=PAGE_UNSET,page_offset,boot_mask;
static bool prepared,finalizing,allowed;
K_MUTEX_DEFINE(lock);
K_SEM_DEFINE(finalize_signal,0,1);
static struct k_work adv_work;
static bool scratch(uint32_t address) {return address>=RESTORE_SCRATCH_START && address<RESTORE_SCRATCH_END;}
static bool valid_page(uint32_t address) {return address<FLASH_SIZE && !(address&(PAGE_SIZE-1)) && !scratch(address);}
static int digest_matches(const void *data,uint32_t address) {
 uint8_t digest[32];size_t length=0;
 psa_status_t status=psa_hash_compute(PSA_ALG_SHA_256,data,PAGE_SIZE,digest,sizeof(digest),&length);
 if(status!=PSA_SUCCESS || length!=32)return -EIO;
 return memcmp(digest,expected_pages[address/PAGE_SIZE],32)==0?0:-EILSEQ;
}
static int query(uint32_t address) {
 if(!valid_page(address))return -EINVAL;
 if(address<RESTORE_BOOT_SIZE) {
  if(!(boot_mask&BIT(address/PAGE_SIZE)))return -ENOENT;
  return digest_matches((uint8_t *)boot+address,address);
 }
 return digest_matches((const void *)(uintptr_t)address,address);
}
static int prepare(void) {
 if(boot_mask!=0xfff)return -ENOENT;
 for(uint32_t a=0;a<FLASH_SIZE;a+=PAGE_SIZE) {
  if(scratch(a))continue;
  int error=query(a);if(error)return error;
 }
 prepared=true;return 0;
}
static ssize_t read_reply(struct bt_conn *c,const struct bt_gatt_attr *a,void *b,uint16_t n,uint16_t off) {
 uint8_t snapshot[20];k_mutex_lock(&lock,K_FOREVER);memcpy(snapshot,reply,20);k_mutex_unlock(&lock);
 return bt_gatt_attr_read(c,a,b,n,off,snapshot,20);
}
static ssize_t request(struct bt_conn *c,const struct bt_gatt_attr *a,const void *buffer,uint16_t length,uint16_t offset,uint8_t flags) {
 ARG_UNUSED(c);ARG_UNUSED(a);
 if(offset || (flags & ~BT_GATT_WRITE_FLAG_CMD) || length<12)return BT_GATT_ERR(BT_ATT_ERR_INVALID_ATTRIBUTE_LEN);
 const uint8_t *in=buffer;uint8_t op=in[1];uint32_t address=sys_get_le32(in+4),arg=sys_get_le32(in+8);
 uint16_t sequence=sys_get_le16(in+2);int rc=0;
 k_mutex_lock(&lock,K_FOREVER);
 if((flags & BT_GATT_WRITE_FLAG_CMD) && op!=1)rc=-EPERM;
 else if(in[0]!=1)rc=-EPROTONOSUPPORT;
 else if(!allowed)rc=-EPERM;
 else if(finalizing && op!=0)rc=-EBUSY;
 else if(prepared && op!=0 && op!=5 && op!=7)rc=-EBUSY;
 else if(op==0) { if(length!=12 || address || arg)rc=-EINVAL; }
 else if(op==1) {
  uint32_t payload=length-12;
  if(!valid_page(address) || payload==0 || arg>PAGE_SIZE || payload>PAGE_SIZE-arg)rc=-EINVAL;
  else {
   if(arg==0) {page_address=address;page_offset=0;}
   if(address!=page_address || arg!=page_offset)rc=-ESPIPE;
   else {memcpy(page+arg,in+12,payload);page_offset+=payload;}
  }
 } else if(op==2) {
  if(length!=12 || arg || address!=page_address || page_offset!=PAGE_SIZE || !valid_page(address))rc=-EINVAL;
  else if((rc=digest_matches(page,address))!=0) {}
  else if(address<RESTORE_BOOT_SIZE) {
   {memcpy((uint8_t *)boot+address,page,PAGE_SIZE);boot_mask|=BIT(address/PAGE_SIZE);}
  } else {
   if(query(address)!=0) {
    rc=flash_erase(flash,address,PAGE_SIZE);
    if(rc==0)rc=flash_write(flash,address,page,PAGE_SIZE);
   }
   if(rc==0)rc=query(address);
  }
 } else if(op==3) {rc=(length==12 && arg==0)?query(address):-EINVAL;}
 else if(op==4) {rc=(length==12 && address==0 && arg==0)?prepare():-EINVAL;}
 else if(op==5) {
  if(length!=12 || address || arg!=0x52535452U || !prepared)rc=-EPERM;
  else finalizing=true;
 } else if(op==7) {
  if(length!=12 || address || arg)rc=-EINVAL;
 } else rc=-ENOTSUP;
 reply[0]=1;reply[1]=op;sys_put_le16(sequence,reply+2);sys_put_le32((uint32_t)rc,reply+4);
 sys_put_le32(op==0?NRF_FICR->DEVICEID[0]:address,reply+8);
 sys_put_le32(op==0?NRF_FICR->DEVICEID[1]:page_offset,reply+12);
 sys_put_le32((allowed?1U:0U)|(prepared?2U:0U)|(finalizing?4U:0U),reply+16);
 bool do_final=finalizing && op==5 && rc==0;
 bool do_reset=rc==0 && op==7;
 k_mutex_unlock(&lock);
 if(do_final)k_sem_give(&finalize_signal);
 if(do_reset)sys_reboot(SYS_REBOOT_COLD);
 return length;
}
BT_GATT_SERVICE_DEFINE(restore_service,BT_GATT_PRIMARY_SERVICE(&service_uuid),
 BT_GATT_CHARACTERISTIC(&command_uuid.uuid,BT_GATT_CHRC_READ|BT_GATT_CHRC_WRITE|BT_GATT_CHRC_WRITE_WITHOUT_RESP,
 BT_GATT_PERM_READ_AUTHEN|BT_GATT_PERM_WRITE_AUTHEN,read_reply,request,NULL));
static const struct bt_data ad[]={BT_DATA_BYTES(BT_DATA_FLAGS,BT_LE_AD_GENERAL|BT_LE_AD_NO_BREDR),BT_DATA_BYTES(BT_DATA_UUID128_ALL,SVC_UUID)};
static const struct bt_data sd[]={BT_DATA(BT_DATA_NAME_COMPLETE,CONFIG_BT_DEVICE_NAME,sizeof(CONFIG_BT_DEVICE_NAME)-1)};
static void advertise(struct k_work *w) {ARG_UNUSED(w);int error=bt_le_adv_start(BT_LE_ADV_CONN_FAST_1,ad,ARRAY_SIZE(ad),sd,ARRAY_SIZE(sd));LOG_INF("Restore advertise: %d",error);}
static void recycled(void){k_work_submit(&adv_work);}
BT_CONN_CB_DEFINE(callbacks)={.recycled=recycled};
int main(void) {
 allowed=NRF_FICR->INFO.PART==0x52840 && NRF_FICR->INFO.VARIANT==0x@VIMAR_CHIP_VARIANT@ && NRF_FICR->DEVICEID[0]==PROBE_UID0 && NRF_FICR->DEVICEID[1]==PROBE_UID1;
 if(!allowed || !device_is_ready(flash)) {LOG_ERR("Refusing non-authorized target or unavailable flash");return 0;}
 if(psa_crypto_init()!=PSA_SUCCESS)return 0;
 uint8_t uicr_digest[32];size_t uicr_length=0;
 if(psa_hash_compute(PSA_ALG_SHA_256,(const void *)0x10001000,4096,uicr_digest,32,&uicr_length)!=PSA_SUCCESS || uicr_length!=32 || memcmp(uicr_digest,expected_uicr,32)!=0) {LOG_ERR("UICR differs from backup; refusing restoration");return 0;}
 bt_addr_le_t address={.type=BT_ADDR_LE_RANDOM,.a={.val=PROBE_MAC_BYTES}};
 int error=bt_id_create(&address,NULL);if(error<0){LOG_ERR("Identity: %d",error);return 0;}
 error=bt_passkey_set(824005);if(error==0)error=bt_enable(NULL);
 if(error){LOG_ERR("BLE init: %d",error);return 0;}
 k_work_init(&adv_work,advertise);k_work_submit(&adv_work);
 LOG_INF("Vimar candidate scratch restorer started, no flash settings backend");
 while(true) {
  k_sem_take(&finalize_signal,K_FOREVER);k_sleep(K_MSEC(750));
  error=bt_disable();
  if(error){LOG_ERR("Cannot stop Bluetooth: %d",error);k_mutex_lock(&lock,K_FOREVER);finalizing=false;prepared=false;k_mutex_unlock(&lock);continue;}
  LOG_INF("Entering SRAM finalizer; irreversible boot rewrite begins");
  irq_lock();restore_finalize_ram(boot);
 }
}
