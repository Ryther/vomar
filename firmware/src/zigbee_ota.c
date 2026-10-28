/* Custom writer: slot1 is independent recovery and is never a DFU target. */
#include "zigbee_ota.h"
#include "platform_io.h"
#include "ota_stage.h"
#include "ota_format.h"
#include "ota_storage.h"
#include "ota_image.h"
#if defined(CONFIG_VIMAR_LOADER_RUNTIME_V2)
#include "loader_runtime_zephyr.h"
#endif
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
#include "ota_split_stage.h"
#include "ota_pair.h"
#include VIMAR_OTA_PAIR_BINDINGS_HEADER
#endif
#include <errno.h>
#include <string.h>
#include <zephyr/app_version.h>
#include <zephyr/drivers/flash.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zigbee/zigbee_error_handler.h>
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
BUILD_ASSERT(CONFIG_MAIN_STACK_SIZE >= 8192);
#endif
LOG_MODULE_REGISTER(vimar_ota,LOG_LEVEL_INF);
static zb_zcl_ota_upgrade_attrs_t attrs;
ZB_ZCL_DECLARE_OTA_UPGRADE_ATTRIB_LIST(vimar_ota_attrs,attrs.upgrade_server,
 &attrs.file_offset,&attrs.file_version,&attrs.stack_version,&attrs.downloaded_file_ver,
 &attrs.downloaded_stack_ver,&attrs.image_status,&attrs.manufacturer,&attrs.image_type,
 &attrs.min_block_reque,&attrs.image_stamp,&attrs.server_addr,&attrs.server_ep,1,64,1440);
BUILD_ASSERT(ARRAY_SIZE(vimar_ota_attrs)==VIMAR_OTA_ATTR_COUNT);
static const struct device *flash=DEVICE_DT_GET(DT_CHOSEN(zephyr_flash_controller));
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
static struct ota_split_transfer transfer;
static bool pair_ready,download_pair_checked;
static uint8_t pair_loader_digest[32];
static struct ota_image_info pair_recovery;
static uint8_t boot_verified_recovery_digest[32];
static uint8_t boot_recovery_file_digest[32],boot_loader_digest[32];
static uint32_t boot_recovery_size;
#else
static struct ota_stage_transfer transfer;
#endif
static uint8_t header[66],page[4096] __aligned(4),block[255];
static uint32_t header_used,page_address,page_used,target_version,total_length;
static uint32_t block_offset;static uint8_t block_length,operation,held_buffer;
static bool active,busy,checked,finishing;
static int work_result;
static struct ota_transaction pending;
static struct k_work work;
static struct k_work_q ota_queue;
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
/* CHECK nests pair/candidate verification with the CC3XX ECDSA backend. */
#if defined(CONFIG_VIMAR_LOADER_RUNTIME_V2)
K_THREAD_STACK_DEFINE(ota_stack,12288);
#else
K_THREAD_STACK_DEFINE(ota_stack,8192);
#endif
#else
K_THREAD_STACK_DEFINE(ota_stack,6144);
#endif

static int flush_page(void)
{
 if(!page_used)return 0;
 bool valid=page_address>=transfer.bounds.start&&page_address<=transfer.bounds.end-4096;
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
 valid=valid||(page_address>=transfer.bounds.second_start&&page_address<=transfer.bounds.second_end-4096);
#endif
 if(!valid)return-EINVAL;
 int rc=flash_erase(flash,page_address,4096);
 if(!rc)rc=flash_write(flash,page_address,page,4096);
 if(!rc){page_used=0;page_address+=4096;
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
 if(page_address==transfer.bounds.end)page_address=transfer.bounds.second_start;
#endif
 memset(page,0xff,sizeof(page));}
 return rc;
}
static int stage_read(void *ctx,uint32_t addr,uint8_t *data,size_t length)
{
 ARG_UNUSED(ctx);
 for(size_t i=0;i<length;i++) data[i]=(addr+i>=page_address&&addr+i<page_address+page_used)?page[addr+i-page_address]:*(const uint8_t*)(uintptr_t)(addr+i);
 return 0;
}
static int stage_write(void *ctx,uint32_t addr,const uint8_t *data,size_t length)
{
 ARG_UNUSED(ctx);
 if(addr!=page_address+page_used)return-EINVAL;
 while(length){size_t n=MIN(length,sizeof(page)-page_used);memcpy(page+page_used,data,n);page_used+=n;data+=n;length-=n;if(page_used==sizeof(page)){int rc=flush_page();if(rc)return rc;}}
 return 0;
}
static int receive_block(void)
{
 uint32_t offset=block_offset;size_t n=block_length;const uint8_t *data=block;
 if(!n || offset>total_length || n>total_length-offset)return-EINVAL;
 if(offset<header_used && offset+n<=header_used)return memcmp(header+offset,data,n)?-EILSEQ:0;
 if(offset<sizeof(header)){
  if(offset!=header_used)return-EINVAL;
  size_t count=MIN(n,sizeof(header)-header_used);
  memcpy(header+header_used,data,count);header_used+=count;offset+=count;data+=count;n-=count;
  if(header_used==sizeof(header)){
   uint32_t payload;
   if(ota_container_header(header,sizeof(header),target_version,total_length,&payload)||payload!=transfer.bounds.payload_size)return-EINVAL;
  }
 }
 if(n){if(header_used!=sizeof(header))return-EINVAL;
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
 return ota_split_accept(&transfer,offset-sizeof(header),data,n);
#else
 return ota_stage_accept(&transfer,offset-sizeof(header),data,n);
#endif
}
 return 0;
}
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
static int split_read(void*ctx,uint32_t off,uint8_t*p,size_t n){
 ARG_UNUSED(ctx);
 while(n){uint32_t physical,available;int rc=ota_split_map(&transfer.bounds,off,&physical,&available);if(rc)return rc;
 size_t take=MIN(n,available);rc=stage_read(NULL,physical,p,take);if(rc)return rc;
 off+=take;p+=take;n-=take;}return 0;
}
static int authenticate_pair(void)
{
#if defined(CONFIG_VIMAR_LOADER_RUNTIME_V2)
 return loader_pair_authenticate_zephyr(pair_loader_digest,&pair_recovery);
#else
 return ota_pair_authenticate((const uint8_t*)0,0x100000,ota_allowed_loaders,ota_allowed_loader_count,
 pair_loader_digest,&pair_recovery);
#endif
}
static int verify_pair(void)
{
 int rc=authenticate_pair();
 if(!rc&&(memcmp(pair_recovery.output_digest,boot_recovery_file_digest,32)||
           memcmp(pair_loader_digest,boot_loader_digest,32)))rc=-EACCES;
 return rc;
}
#endif
static int check_image(void)
{
 if(header_used!=sizeof(header)||transfer.next_offset!=transfer.bounds.payload_size)return-EINVAL;
 int rc=flush_page();if(rc)return rc;
 struct ota_image_info info;
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
 rc=verify_pair();if(rc)return rc;
 const struct ota_reader reader={.size=transfer.bounds.payload_size,.profile=2,.read=split_read};
 rc=ota_image_authenticate_reader(&reader,transfer.bounds.start-OTA_PRIMARY_START,&info);
#else
 rc=ota_image_authenticate((const uint8_t*)(uintptr_t)transfer.bounds.start,transfer.bounds.payload_size,
  transfer.bounds.start-OTA_PRIMARY_START,&info);
#endif
 if(rc)return rc;
 /* Signed version must agree with the untrusted Zigbee envelope. */
 uint32_t v=((uint32_t)info.image_version[0]<<24)|((uint32_t)info.image_version[1]<<16)|((uint32_t)info.image_version[2]<<8)|info.image_version[4];
 if(info.image_version[3]||info.image_version[5]||info.image_version[6]||info.image_version[7]||v!=target_version)return-EINVAL;
 struct ota_transaction old;uint32_t generation=ota_storage_load(&old)?1:old.generation+1;
 pending=(struct ota_transaction){.format_version=OTA_TRANSACTION_VERSION,.generation=generation,
  .state=OTA_TRANSACTION_PENDING,.stage_start=transfer.bounds.start,.stage_end=transfer.bounds.end,
  .candidate_size=transfer.bounds.payload_size,.signed_image_size=info.output_size};
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
 pending.format_version=2;pending.second_start=transfer.bounds.second_start;pending.second_end=transfer.bounds.second_end;
 memcpy(pending.loader_digest,pair_loader_digest,32);memcpy(pending.recovery_digest,pair_recovery.output_digest,32);
#endif
 memcpy(pending.candidate_digest,info.source_digest,32);memcpy(pending.final_digest,info.signed_digest,32);
 return ota_transaction_validate(&pending)?-EINVAL:0;
}
static void resume(zb_uint8_t buffer)
{
 bool ok=work_result==0;
 if(operation==ZB_ZCL_OTA_UPGRADE_STATUS_CHECK)checked=ok;
 if(!ok){active=false;checked=false;LOG_ERR("OTA operation %u failed: %d",operation,work_result);}
 busy=false;
 zb_zcl_ota_upgrade_resume_client(buffer,ok?ZB_ZCL_OTA_UPGRADE_STATUS_OK:ZB_ZCL_OTA_UPGRADE_STATUS_ERROR);
}
static void worker(struct k_work *item)
{
 ARG_UNUSED(item);
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
 if(!download_pair_checked){work_result=verify_pair();if(!work_result)download_pair_checked=true;}
 else work_result=0;
 if(!work_result)
#endif
 work_result=operation==ZB_ZCL_OTA_UPGRADE_STATUS_CHECK?check_image():receive_block();
 /* ZBOSS only runs its continuation after restoring the held buffer metadata. */
 while(ZB_SCHEDULE_APP_CALLBACK(resume,held_buffer)!=RET_OK)k_sleep(K_MSEC(10));
}
static void reboot_for_install(zb_uint8_t unused)
{
 ARG_UNUSED(unused);
 int rc=ota_storage_save(&pending);
 if(!rc)rc=platform_io_request_recovery();
 if(rc)LOG_ERR("OTA installation request failed:%d",rc);
}
void zigbee_ota_callback(zb_bufid_t buffer)
{
 zb_zcl_device_callback_param_t *p=ZB_BUF_GET_PARAM(buffer,zb_zcl_device_callback_param_t);
 zb_zcl_ota_upgrade_value_param_t *v=&p->cb_param.ota_value_param;
 p->status=RET_OK;
 switch(v->upgrade_status){
 case ZB_ZCL_OTA_UPGRADE_STATUS_START:{
  if(busy||active||finishing||v->upgrade.start.manufacturer!=VIMAR_OTA_MANUFACTURER||v->upgrade.start.image_type!=VIMAR_OTA_IMAGE_TYPE||v->upgrade.start.file_version<=attrs.file_version||v->upgrade.start.file_length<=sizeof(header)){v->upgrade_status=ZB_ZCL_OTA_UPGRADE_STATUS_ERROR;break;}
  uint32_t region,size;int rc=ota_primary_extent((const uint8_t*)OTA_PRIMARY_START,OTA_PRIMARY_END-OTA_PRIMARY_START,&region,&size);
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
  if(!pair_ready)rc=-EACCES;
  if(!rc)rc=ota_split_plan(OTA_PRIMARY_START+size,v->upgrade.start.file_length-sizeof(header),OTA_PRIMARY_START+size,
   0xb0000+boot_recovery_size,&transfer.bounds);
  download_pair_checked=false;
#else
  if(!rc)rc=ota_stage_plan(OTA_PRIMARY_START+size,v->upgrade.start.file_length-sizeof(header),OTA_PRIMARY_START+size,&transfer.bounds);
#endif
  if(rc){LOG_ERR("OTA no safe staging space:%d",rc);v->upgrade_status=ZB_ZCL_OTA_UPGRADE_STATUS_ERROR;break;}
  target_version=v->upgrade.start.file_version;total_length=v->upgrade.start.file_length;
  transfer.next_offset=0;transfer.read=stage_read;transfer.write=stage_write;
  header_used=page_used=0;page_address=transfer.bounds.start;memset(page,0xff,sizeof(page));
  active=true;checked=false;v->upgrade_status=ZB_ZCL_OTA_UPGRADE_STATUS_OK;
  LOG_INF("OTA start version %08x, %u bytes, stage %x",target_version,total_length,page_address);break;}
 case ZB_ZCL_OTA_UPGRADE_STATUS_RECEIVE:
 case ZB_ZCL_OTA_UPGRADE_STATUS_CHECK:
  if(!active||busy){v->upgrade_status=ZB_ZCL_OTA_UPGRADE_STATUS_ERROR;break;}
  operation=v->upgrade_status;held_buffer=buffer;
  if(operation==ZB_ZCL_OTA_UPGRADE_STATUS_RECEIVE){block_offset=v->upgrade.receive.file_offset;block_length=v->upgrade.receive.data_length;memcpy(block,v->upgrade.receive.block_data,block_length);}
  busy=true;v->upgrade_status=ZB_ZCL_OTA_UPGRADE_STATUS_BUSY;k_work_submit_to_queue(&ota_queue,&work);break;
 case ZB_ZCL_OTA_UPGRADE_STATUS_APPLY:
  v->upgrade_status=checked?ZB_ZCL_OTA_UPGRADE_STATUS_OK:ZB_ZCL_OTA_UPGRADE_STATUS_ERROR;break;
 case ZB_ZCL_OTA_UPGRADE_STATUS_FINISH:
  if(!checked||!active){v->upgrade_status=ZB_ZCL_OTA_UPGRADE_STATUS_ERROR;break;}
  finishing=true;
  if(ZB_SCHEDULE_APP_ALARM(reboot_for_install,0,ZB_MILLISECONDS_TO_BEACON_INTERVAL(1000))!=RET_OK){finishing=false;v->upgrade_status=ZB_ZCL_OTA_UPGRADE_STATUS_ERROR;break;}
  active=false;v->upgrade_status=ZB_ZCL_OTA_UPGRADE_STATUS_OK;break;
 case ZB_ZCL_OTA_UPGRADE_STATUS_ABORT:active=false;checked=false;break;
 default:p->status=RET_NOT_IMPLEMENTED;break;
 }
}
bool zigbee_ota_recovery_snapshot(uint8_t digest[32])
{
 if(!digest)return false;
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
 if(pair_ready){memcpy(digest,boot_verified_recovery_digest,32);return true;}
#endif
 memset(digest,0,32);return false;
}
void zigbee_ota_init(void)
{
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
 pair_ready=authenticate_pair()==0;
 if(pair_ready){
  memcpy(boot_verified_recovery_digest,pair_recovery.signed_digest,32);
  memcpy(boot_recovery_file_digest,pair_recovery.output_digest,32);
  memcpy(boot_loader_digest,pair_loader_digest,32);boot_recovery_size=pair_recovery.output_size;
 }else{
  memset(boot_verified_recovery_digest,0,32);memset(boot_recovery_file_digest,0,32);
  memset(boot_loader_digest,0,32);boot_recovery_size=0;
 }
#endif
 memset(&attrs,0,sizeof(attrs));memset(attrs.upgrade_server,0xff,8);
 attrs.file_version=((uint32_t)APP_VERSION_MAJOR<<24)|((uint32_t)APP_VERSION_MINOR<<16)|((uint32_t)APP_PATCHLEVEL<<8)|APP_TWEAK;
 attrs.stack_version=2;attrs.downloaded_file_ver=0xffffffff;attrs.downloaded_stack_ver=0xffff;
 attrs.manufacturer=VIMAR_OTA_MANUFACTURER;attrs.image_type=VIMAR_OTA_IMAGE_TYPE;attrs.server_addr=0xffff;attrs.server_ep=0xff;
 k_work_init(&work,worker);k_work_queue_start(&ota_queue,ota_stack,K_THREAD_STACK_SIZEOF(ota_stack),7,NULL);
}

void zigbee_ota_joined(void)
{
 /* Discovery is restart-safe in ZBOSS and preserves an active transfer. */
 (void)zb_buf_get_out_delayed(zb_zcl_ota_upgrade_init_client);
}
