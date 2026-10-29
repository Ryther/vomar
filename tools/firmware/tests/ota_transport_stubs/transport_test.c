#define _GNU_SOURCE
#include <assert.h>
#include <sys/mman.h>
#include <errno.h>
#include "fake.h"
#include "ota_format.h"
static uint8_t primary[64];
static int host_extent(const uint8_t *mapped,size_t capacity,uint32_t *region,uint32_t *total)
{
 assert((uintptr_t)mapped==0xc000 && capacity==0xa4000);
 return ota_primary_extent(primary,sizeof(primary),region,total);
}
#define ota_primary_extent host_extent
#include "../../../../firmware/src/zigbee_ota.c"
#undef ota_primary_extent

zb_zcl_device_callback_param_t fake_param;
const struct device fake_device={0};
static struct k_work *queued_work;
static void(*queued_callback)(uint8_t),(*queued_alarm)(uint8_t);
static uint8_t callback_value,alarm_value,last_resume;
static int alarm_error;
static unsigned erases,writes,resumes,saves,recovery;
static bool high_version;
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
#define PAYLOAD_SIZE 256429
static uint8_t container[66+PAYLOAD_SIZE];
static int pair_error;
static uint8_t accepted_pair=3,accepted_loader=4;
static bool replace_recovery_on_check;
static unsigned pair_checks;
#if defined(CONFIG_VIMAR_LOADER_RUNTIME_V2)
int loader_pair_authenticate_zephyr(uint8_t loader[32],struct ota_image_info*info){
#else
int ota_pair_authenticate(const uint8_t*m,size_t n,const uint8_t(*a)[32],size_t count,uint8_t loader[32],struct ota_image_info*info){
 (void)m;(void)n;assert(a&&count);
#endif
 if(pair_error)return pair_error;
 ++pair_checks;memset(info,0,sizeof(*info));info->output_size=197006;
 info->authenticated_profile=2;info->authenticated_role=2;
 info->output_digest[0]=accepted_pair;info->signed_digest[0]=accepted_pair+2;loader[0]=accepted_loader;return 0;
}
int ota_image_authenticate_reader(const struct ota_reader*r,uint32_t limit,struct ota_image_info*info){
 static uint8_t data[PAYLOAD_SIZE];assert(r->profile==2&&r->size==PAYLOAD_SIZE&&limit==transfer.bounds.start-OTA_PRIMARY_START);
 assert(!ota_reader_read(r,0,data,sizeof(data))&&!memcmp(data,container+66,sizeof(data)));
 memset(info,0,sizeof(*info));info->output_size=64;info->image_version[0]=1;info->image_version[2]=1;info->image_version[3]=high_version?1:0;
 info->source_digest[0]=1;info->signed_digest[0]=2;return 0;
}
#else
#define PAYLOAD_SIZE 4300
static uint8_t container[66+PAYLOAD_SIZE];
#endif
static void p16(uint8_t*p,uint16_t n){p[0]=(uint8_t)n;p[1]=(uint8_t)(n>>8);}
static void p32(uint8_t*p,uint32_t n){p16(p,(uint16_t)n);p16(p+2,(uint16_t)(n>>16));}
int flash_erase(const struct device*d,uint32_t address,size_t n)
{
 assert(d==&fake_device && n==4096);
 bool safe=address>=transfer.bounds.start&&address+n<=transfer.bounds.end;
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
 safe=safe||(address>=transfer.bounds.second_start&&address+n<=transfer.bounds.second_end);
#endif
 assert(safe);
 memset((void*)(uintptr_t)address,0xff,n);erases++;return 0;
}
int flash_write(const struct device*d,uint32_t address,const void*data,size_t n)
{
 assert(d==&fake_device && n==4096);
 bool safe=address>=transfer.bounds.start&&address+n<=transfer.bounds.end;
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
 safe=safe||(address>=transfer.bounds.second_start&&address+n<=transfer.bounds.second_end);
#endif
 assert(safe);
 memcpy((void*)(uintptr_t)address,data,n);writes++;return 0;
}
int k_work_submit_to_queue(struct k_work_q*q,struct k_work*w)
{assert(q==&ota_queue && !queued_work);queued_work=w;return 1;}
int fake_schedule(void(*cb)(uint8_t),uint8_t value)
{assert(!queued_callback);queued_callback=cb;callback_value=value;return RET_OK;}
int fake_alarm(void(*cb)(uint8_t),uint8_t value,unsigned delay)
{assert(delay==1000);if(alarm_error)return alarm_error;assert(!queued_alarm);queued_alarm=cb;alarm_value=value;return RET_OK;}
void zb_zcl_ota_upgrade_resume_client(uint8_t buffer,uint8_t status)
{assert(buffer==1 && !busy);last_resume=status;resumes++;}
void zb_zcl_ota_upgrade_init_client(uint8_t buffer){(void)buffer;}
int zb_buf_get_out_delayed(void(*cb)(uint8_t)){(void)cb;return 0;}
int ota_storage_load(struct ota_transaction*tx){(void)tx;return -ENOENT;}
int ota_storage_save(const struct ota_transaction*tx)
{assert(ota_transaction_validate(tx)==0 && tx->state==OTA_TRANSACTION_PENDING);saves++;return 0;}
int platform_io_request_recovery(void){recovery++;return 0;}
int ota_image_authenticate(const uint8_t*source,size_t n,uint32_t limit,struct ota_image_info*info)
{
 assert((uintptr_t)source==transfer.bounds.start && n==4300 && limit==transfer.bounds.start-OTA_PRIMARY_START);
 assert(memcmp(source,container+66,n)==0);
 memset(info,0,sizeof(*info));info->output_size=64;
 info->image_version[0]=1;info->image_version[2]=1;info->image_version[3]=high_version?1:0;
 info->source_digest[0]=1;info->signed_digest[0]=2;return 0;
}
static unsigned callback(unsigned status)
{fake_param.cb_param.ota_value_param.upgrade_status=(uint8_t)status;zigbee_ota_callback(1);return fake_param.cb_param.ota_value_param.upgrade_status;}
static void drain(void)
{
 assert(queued_work && !queued_callback);
 struct k_work*w=queued_work;queued_work=NULL;w->handler(w);
 assert(queued_callback && busy);
 void(*cb)(uint8_t)=queued_callback;queued_callback=NULL;cb(callback_value);
 assert(!busy);
}
static unsigned start(uint16_t type,uint32_t version,uint32_t length)
{
 fake_param.cb_param.ota_value_param.upgrade.start.manufacturer=VIMAR_OTA_MANUFACTURER;
 fake_param.cb_param.ota_value_param.upgrade.start.image_type=type;
 fake_param.cb_param.ota_value_param.upgrade.start.file_version=version;
 fake_param.cb_param.ota_value_param.upgrade.start.file_length=length;
 return callback(ZB_ZCL_OTA_UPGRADE_STATUS_START);
}
static unsigned receive(uint32_t offset,size_t n)
{
 assert(n<=255 && offset+n<=sizeof(container));
 fake_param.cb_param.ota_value_param.upgrade.receive.file_offset=offset;
 fake_param.cb_param.ota_value_param.upgrade.receive.data_length=(uint8_t)n;
 fake_param.cb_param.ota_value_param.upgrade.receive.block_data=container+offset;
 unsigned before=resumes;
 assert(callback(ZB_ZCL_OTA_UPGRADE_STATUS_RECEIVE)==ZB_ZCL_OTA_UPGRADE_STATUS_BUSY);
 assert(resumes==before);drain();return last_resume;
}
static void reset(void)
{
 assert(!queued_work && !queued_callback);
 active=busy=checked=finishing=false;alarm_error=0;queued_alarm=NULL;
 erases=writes=resumes=saves=recovery=0;high_version=false;zigbee_ota_init();
 memset(container,0,sizeof(container));p32(container,0x0beef11e);p16(container+4,0x100);p16(container+6,60);
 p16(container+8,4);p16(container+10,0xfff1);p16(container+12,0x3085);p32(container+14,0x01000100);
 p16(container+18,2);p32(container+52,sizeof(container));p16(container+56,1);p16(container+58,1);p32(container+62,PAYLOAD_SIZE);
 for(size_t i=66;i<sizeof(container);i++)container[i]=(uint8_t)i;
}
static void download(void)
{
 assert(start(VIMAR_OTA_IMAGE_TYPE,0x01000100,sizeof(container))==ZB_ZCL_OTA_UPGRADE_STATUS_OK);
 assert(receive(0,17)==ZB_ZCL_OTA_UPGRADE_STATUS_OK);
 assert(receive(17,80)==ZB_ZCL_OTA_UPGRADE_STATUS_OK); /* crosses 66-byte header */
 assert(receive(66,31)==ZB_ZCL_OTA_UPGRADE_STATUS_OK); /* buffered duplicate */
 for(uint32_t off=97;off<sizeof(container);){size_t n=MIN(211,sizeof(container)-off);assert(receive(off,n)==ZB_ZCL_OTA_UPGRADE_STATUS_OK);off+=(uint32_t)n;}
 assert(erases==PAYLOAD_SIZE/4096 && writes==PAYLOAD_SIZE/4096 && !saves && !recovery);
 assert(receive(66,31)==ZB_ZCL_OTA_UPGRADE_STATUS_OK); /* persisted duplicate */
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
 if(replace_recovery_on_check)accepted_pair++;
#endif
 assert(callback(ZB_ZCL_OTA_UPGRADE_STATUS_CHECK)==ZB_ZCL_OTA_UPGRADE_STATUS_BUSY);drain();
}
int main(void)
{
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
 assert(sizeof(ota_stack)>=8192); /* CC3XX CHECK path exceeds6KiB. */
#endif
 assert(mmap((void*)0x10000,0xe0000,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED,-1,0)!=(void*)-1);
 p32(primary,0x96f3b83d);p16(primary+8,32);p32(primary+12,16);p16(primary+48,0x6907);p16(primary+50,4);
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
 pair_error=-EACCES;reset();assert(start(VIMAR_OTA_IMAGE_TYPE,0x01000100,sizeof(container))==ZB_ZCL_OTA_UPGRADE_STATUS_ERROR&&!erases);
 pair_error=0;reset();assert(start(VIMAR_OTA_IMAGE_TYPE,0x01000100,sizeof(container))==ZB_ZCL_OTA_UPGRADE_STATUS_OK);
 pair_error=-EACCES;assert(receive(0,80)==ZB_ZCL_OTA_UPGRADE_STATUS_ERROR&&!erases&&!writes);pair_error=0;
#endif
 uint8_t diagnostic_digest[32];
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
 pair_error=-EACCES;reset();memset(diagnostic_digest,0xaa,32);assert(!zigbee_ota_recovery_snapshot(diagnostic_digest));
 for(unsigned i=0;i<32;i++)assert(diagnostic_digest[i]==0);
 pair_error=0;reset();assert(zigbee_ota_recovery_snapshot(diagnostic_digest)&&diagnostic_digest[0]==5);
 memset(pair_recovery.output_digest,0x77,32);memset(pair_recovery.signed_digest,0x88,32);assert(zigbee_ota_recovery_snapshot(diagnostic_digest)&&diagnostic_digest[0]==5); /* worker output cannot mutate boot proof */
 pair_error=-EACCES;assert(zigbee_ota_recovery_snapshot(diagnostic_digest)&&diagnostic_digest[0]==5); /* getter does not call verifier or write */
 pair_error=0;
#else
 reset();memset(diagnostic_digest,0xaa,32);assert(!zigbee_ota_recovery_snapshot(diagnostic_digest));
 for(unsigned i=0;i<32;i++)assert(diagnostic_digest[i]==0);
#endif
 assert(!erases&&!writes&&!saves&&!recovery);
 reset();assert(start(1,0x01000100,sizeof(container))==ZB_ZCL_OTA_UPGRADE_STATUS_ERROR);
 assert(start(VIMAR_OTA_IMAGE_TYPE,attrs.file_version,sizeof(container))==ZB_ZCL_OTA_UPGRADE_STATUS_ERROR);
 assert(start(VIMAR_OTA_IMAGE_TYPE,0x01000100,UINT32_MAX)==ZB_ZCL_OTA_UPGRADE_STATUS_ERROR);
 assert(!erases && !writes);
 download();assert(checked && erases==(PAYLOAD_SIZE+4095)/4096 && !saves && !recovery);
 assert(callback(ZB_ZCL_OTA_UPGRADE_STATUS_APPLY)==ZB_ZCL_OTA_UPGRADE_STATUS_OK);
 alarm_error=-1;assert(callback(ZB_ZCL_OTA_UPGRADE_STATUS_FINISH)==ZB_ZCL_OTA_UPGRADE_STATUS_ERROR && !finishing && !queued_alarm);
 alarm_error=0;assert(callback(ZB_ZCL_OTA_UPGRADE_STATUS_FINISH)==ZB_ZCL_OTA_UPGRADE_STATUS_OK && finishing);
 assert(start(VIMAR_OTA_IMAGE_TYPE,0x01000200,sizeof(container))==ZB_ZCL_OTA_UPGRADE_STATUS_ERROR);
 assert(callback(ZB_ZCL_OTA_UPGRADE_STATUS_FINISH)==ZB_ZCL_OTA_UPGRADE_STATUS_ERROR);
 assert(!saves && !recovery);queued_alarm(alarm_value);assert(saves==1 && recovery==1);
 reset();high_version=true;download();assert(!checked && last_resume==ZB_ZCL_OTA_UPGRADE_STATUS_ERROR && !saves);
 reset();assert(start(VIMAR_OTA_IMAGE_TYPE,0x01000100,sizeof(container))==ZB_ZCL_OTA_UPGRADE_STATUS_OK);
 assert(receive(0,66)==ZB_ZCL_OTA_UPGRADE_STATUS_OK);
 assert(receive(67,1)==ZB_ZCL_OTA_UPGRADE_STATUS_ERROR && !writes && !erases); /* gap aborts safely */
 reset();assert(start(VIMAR_OTA_IMAGE_TYPE,0x01000100,sizeof(container))==ZB_ZCL_OTA_UPGRADE_STATUS_OK);
 assert(receive(0,80)==ZB_ZCL_OTA_UPGRADE_STATUS_OK);container[66]^=1;
 assert(receive(66,1)==ZB_ZCL_OTA_UPGRADE_STATUS_ERROR && !writes && !erases);
#if defined(CONFIG_VIMAR_OTA_SPLIT_STAGING)
 /* The same compiled MAIN accepts every authenticated recovery of this ABI.
  * Each transaction preserves its actual recovery, including a new file hash. */
 const uint8_t versions[]={3,7,9,33};
 for(size_t v=0;v<sizeof(versions);v++){
  accepted_pair=versions[v];pair_checks=0;reset();
  assert(pair_ready&&pair_checks==1);
  assert(zigbee_ota_recovery_snapshot(diagnostic_digest)&&diagnostic_digest[0]==accepted_pair+2);
  download();assert(checked&&pending.recovery_digest[0]==accepted_pair);
  assert(pending.loader_digest[0]==4);
 }
 pair_error=-EACCES;reset();
 assert(!pair_ready&&!zigbee_ota_recovery_snapshot(diagnostic_digest));
 assert(start(VIMAR_OTA_IMAGE_TYPE,0x01000100,sizeof(container))==ZB_ZCL_OTA_UPGRADE_STATUS_ERROR);
 assert(!erases&&!writes&&!saves&&!recovery);
 pair_error=0;
 accepted_pair=3;reset();assert(pair_ready);
 assert(start(VIMAR_OTA_IMAGE_TYPE,0x01000100,sizeof(container))==ZB_ZCL_OTA_UPGRADE_STATUS_OK);
 accepted_pair=7;assert(receive(0,80)==ZB_ZCL_OTA_UPGRADE_STATUS_ERROR);
 assert(!erases&&!writes&&!saves&&!recovery);
 accepted_pair=3;accepted_loader=4;reset();
 assert(start(VIMAR_OTA_IMAGE_TYPE,0x01000100,sizeof(container))==ZB_ZCL_OTA_UPGRADE_STATUS_OK);
 accepted_loader=5;assert(receive(0,80)==ZB_ZCL_OTA_UPGRADE_STATUS_ERROR);
 assert(!erases&&!writes&&!saves&&!recovery);
 accepted_loader=4;reset();replace_recovery_on_check=true;download();
 assert(!checked&&last_resume==ZB_ZCL_OTA_UPGRADE_STATUS_ERROR&&!saves&&!recovery);
 replace_recovery_on_check=false;accepted_pair=3;reset();assert(pair_ready);
#endif
 return 0;
}
