/* Includes private callbacks only in this host test translation unit. */
#include "recovery_exit_zephyr.c"
#include <assert.h>
#include <stdio.h>
#include <string.h>

uint64_t fake_now;
struct k_work *queued_exit;
static bool marker_present;
static unsigned image_lock_depth, verify_calls, flush_calls, clear_calls, reboot_calls;
static int verify_error;
static int store_error;
static bool migration_image;
static int preflight_error;
static uint8_t live_hash[32]={1};

ssize_t settings_load_one(const char *key,void *data,size_t length)
{
 assert(!strcmp(key,"vimar/recovery_upload")&&length==1);
 if(marker_present){*(uint8_t *)data=1;return 1;}return 0;
}
int settings_save_one(const char *key,const void *data,size_t length)
{
 assert(gate.depth==1&&!strcmp(key,"vimar/recovery_upload"));
 assert(length==1&&*(const uint8_t *)data==1);
 if(store_error)return store_error;
 marker_present=true;return 0;
}
int settings_delete(const char *key)
{
 assert(gate.depth==1&&!strcmp(key,"vimar/recovery_upload"));
 marker_present=false;return 0;
}
void img_mgmt_take_lock(void){assert(!image_lock_depth);image_lock_depth++;}
void img_mgmt_release_lock(void){assert(image_lock_depth==1);image_lock_depth--;}
int recovery_primary_validate(const uint8_t *data,size_t length)
{
 assert(data==(const uint8_t *)RECOVERY_PRIMARY_BASE&&length==RECOVERY_PRIMARY_CAPACITY);
 assert(gate.depth==1&&image_lock_depth==1);verify_calls++;return verify_error?verify_error:migration_image?-EACCES:0;
}
int recovery_primary_validate_upload(const uint8_t *data,size_t length)
{
 assert(data==(const uint8_t *)RECOVERY_PRIMARY_BASE&&length==RECOVERY_PRIMARY_CAPACITY);
 assert(gate.depth==1&&image_lock_depth==1);verify_calls++;return verify_error;
}
int recovery_primary_validate_migration(const uint8_t *data,size_t length,const uint8_t hash[32])
{
 assert(data==(const uint8_t *)RECOVERY_PRIMARY_BASE&&length==RECOVERY_PRIMARY_CAPACITY);
 assert(gate.depth==1&&image_lock_depth==1);verify_calls++;
 return verify_error?verify_error:!migration_image||memcmp(hash,live_hash,32)?-EACCES:0;
}
int recovery_migration_preflight(void)
{assert(gate.depth==1&&image_lock_depth==1);return preflight_error;}
int vimar_power_protection_flush(void)
{assert(gate.depth==1&&image_lock_depth==1);flush_calls++;return 0;}
bool vimar_power_protection_status_blocked(void){return false;}
int bootmode_clear(void)
{assert(gate.depth==1&&image_lock_depth==1);clear_calls++;return 0;}
void sys_reboot(int kind)
{assert(kind==SYS_REBOOT_COLD&&gate.depth==1&&image_lock_depth==1);reboot_calls++;}
void vimar_boot_trace_snapshot(struct boot_trace_entry *out)
{*out=(struct boot_trace_entry){.reason=BOOT_REASON_CHORD,.image=BOOT_IMAGE_RECOVERY};}
int vimar_led_init(void){return 0;}
int vimar_led_render(const struct led_output *out,uint64_t elapsed)
{(void)out;(void)elapsed;return 0;}

static void command_group(uint32_t event,unsigned group_id,unsigned id,unsigned op_or_error)
{
 struct mgmt_evt_op_cmd_arg arg={.group=(uint16_t)group_id,.id=(uint8_t)id};
 if(event==MGMT_EVT_OP_CMD_RECV)arg.op=(uint8_t)op_or_error;
 else arg.err=(int)op_or_error;
 int32_t rc=0;uint16_t group=0;bool abort_more=false;
 assert(commands.callback(event,MGMT_CB_OK,&rc,&group,&abort_more,&arg,sizeof(arg))==MGMT_CB_OK);
 assert(!rc&&!abort_more&&!gate.depth);
}
static void command(uint32_t event,unsigned id,unsigned op_or_error)
{command_group(event,MGMT_GROUP_ID_IMAGE,id,op_or_error);}
static void image(uint32_t event)
{
 int32_t rc=0;uint16_t group=0;bool abort_more=false;
 /* The actual SDK invokes image callbacks while owning its image mutex. */
 img_mgmt_take_lock();
 assert(images.callback(event,MGMT_CB_OK,&rc,&group,&abort_more,NULL,0)==MGMT_CB_OK);
 img_mgmt_release_lock();assert(!gate.depth);
}
static void begin_upload(void)
{command(MGMT_EVT_OP_CMD_RECV,IMG_MGMT_ID_UPLOAD,MGMT_OP_WRITE);}
static void done_upload(unsigned error)
{command(MGMT_EVT_OP_CMD_DONE,IMG_MGMT_ID_UPLOAD,error);}
static void complete_retry(void)
{
 begin_upload();image(MGMT_EVT_OP_IMG_MGMT_DFU_STARTED);
 image(MGMT_EVT_OP_IMG_MGMT_DFU_PENDING);done_upload(0);
 assert(!control.partial&&!control.session&&!control.command_busy&&!marker_present);
}
static void assert_recovery(void)
{assert(recovery_session_led_mode(&session)==WIRELESS_STATUS_LED_RECOVERY);}
static void manual_attempt(void)
{manual_exit_pending=true;exit_work.handler(&exit_work);assert(!gate.depth&&!image_lock_depth);}
static void migration_begin(void)
{
 migration_image=true;complete_retry();
 command_group(MGMT_EVT_OP_CMD_RECV,0x8042,0,MGMT_OP_WRITE);
 assert(!recovery_exit_zephyr_migration_request(live_hash));
 assert(control.exiting&&control.migration_pending&&!control.migration_ready&&!reboot_calls);
}
static void mutation_refused(void)
{
 struct mgmt_evt_op_cmd_arg arg={.group=MGMT_GROUP_ID_IMAGE,.id=IMG_MGMT_ID_UPLOAD,.op=MGMT_OP_WRITE};
 int32_t rc=0;uint16_t group=0;bool abort_more=false;
 assert(commands.callback(MGMT_EVT_OP_CMD_RECV,MGMT_CB_OK,&rc,&group,&abort_more,&arg,sizeof(arg))==MGMT_CB_ERROR_RC);
 assert(rc==MGMT_ERR_EBUSY&&abort_more&&!marker_present);
}

int main(int argc,char **argv)
{
 assert(argc==2);
 if(!strcmp(argv[1],"partial_gate"))marker_present=true;
 recovery_exit_zephyr_init(0,true);
 if(!strcmp(argv[1],"disconnect")){
  begin_upload();image(MGMT_EVT_OP_IMG_MGMT_DFU_STARTED);
  assert(control.command_busy&&control.session&&control.partial&&marker_present);
  /* Real SDK disconnect sends no DFU_STOPPED and may precede CMD_DONE. */
  recovery_exit_zephyr_disconnected();
  assert_recovery();
  assert(control.command_busy&&control.partial&&control.durable&&marker_present);
  assert(!control.session);
  done_upload(0);manual_attempt();
  assert(!verify_calls&&!reboot_calls&&marker_present);
 }else if(!strcmp(argv[1],"stopped_retry")){
  begin_upload();image(MGMT_EVT_OP_IMG_MGMT_DFU_STARTED);
  image(MGMT_EVT_OP_IMG_MGMT_DFU_STOPPED);done_upload(0);
  /* No poll may be necessary to permanently remember the upload fault. */
  complete_retry();assert_recovery();
  fake_now=120000;poll_work.work.handler(&poll_work.work);
  assert(!queued_exit&&!reboot_calls);
  manual_attempt();assert(reboot_calls==1);
 }else if(!strcmp(argv[1],"early_error_retry")){
  begin_upload();
  /* SDK rejects malformed CBOR before STARTED or STOPPED can be emitted. */
  done_upload(MGMT_ERR_EINVAL);
  complete_retry();
  assert_recovery();
  fake_now=120000;poll_work.work.handler(&poll_work.work);
  assert(!queued_exit&&!reboot_calls);
 }else if(!strcmp(argv[1],"stale_timeout")){
  fake_now=60000;poll_work.work.handler(&poll_work.work);assert(queued_exit);
  fake_now=60001;command(MGMT_EVT_OP_CMD_RECV,0,MGMT_OP_READ);
  fake_now=60002;command(MGMT_EVT_OP_CMD_DONE,0,0);
  fake_now=60003;queued_exit->handler(queued_exit);queued_exit=NULL;
  assert(!verify_calls&&!reboot_calls);
  fake_now=120001;poll_work.work.handler(&poll_work.work);assert(!queued_exit);
  fake_now=120002;poll_work.work.handler(&poll_work.work);assert(queued_exit);
  queued_exit->handler(queued_exit);
  assert(verify_calls==1&&flush_calls==1&&clear_calls==1&&reboot_calls==1);
 }else if(!strcmp(argv[1],"partial_gate")){
  assert_recovery();manual_attempt();
  assert(marker_present&&control.partial&&!verify_calls&&!reboot_calls);
 }else if(!strcmp(argv[1],"invalid_main_gate")){
  verify_error=-EACCES;fake_now=60000;
  poll_work.work.handler(&poll_work.work);assert(queued_exit);
  queued_exit->handler(queued_exit);queued_exit=NULL;assert_recovery();
  assert(verify_calls==1&&!flush_calls&&!clear_calls&&!reboot_calls);
  fake_now=120000;poll_work.work.handler(&poll_work.work);assert(!queued_exit);
  manual_attempt();assert(verify_calls==2&&!reboot_calls);
 }else if(!strcmp(argv[1],"history_activity")){
  fake_now=100;command_group(MGMT_EVT_OP_CMD_RECV,0x8041,0,MGMT_OP_READ);
  assert(control.command_busy&&!control.partial&&!marker_present&&session.last_activity_ms==100);
  manual_attempt();assert(!verify_calls&&!reboot_calls);
  fake_now=200;command_group(MGMT_EVT_OP_CMD_DONE,0x8041,0,0);
  assert(!control.command_busy&&session.last_activity_ms==200);
  fake_now=60199;poll_work.work.handler(&poll_work.work);
  assert(!queued_exit&&!verify_calls&&!reboot_calls&&!marker_present);
 }else if(!strcmp(argv[1],"migration_upload")){
  migration_image=true;complete_retry();
  manual_attempt();assert(!reboot_calls&&!control.partial&&!marker_present);
 }else if(!strcmp(argv[1],"migration_ack")){
  migration_begin();mutation_refused();
  /* No work can execute before successful transport output / CMD_DONE. */
  assert(!queued_exit);exit_work.handler(&exit_work);assert(!reboot_calls);
  command_group(MGMT_EVT_OP_CMD_DONE,0x8042,0,0);
  assert(queued_exit&&control.migration_ready);mutation_refused();
  command_group(MGMT_EVT_OP_CMD_DONE,MGMT_GROUP_ID_IMAGE,IMG_MGMT_ID_UPLOAD,10);
  command_group(MGMT_EVT_OP_CMD_DONE,0x8042,0,10);
  assert(control.migration_pending&&control.migration_ready&&control.exiting);
  queued_exit->handler(queued_exit);
  assert(reboot_calls==1&&clear_calls==1&&flush_calls==2);
 }else if(!strcmp(argv[1],"migration_output_error")){
  migration_begin();command_group(MGMT_EVT_OP_CMD_DONE,0x8042,0,5);
  assert(!queued_exit&&!control.exiting&&!control.migration_pending&&!reboot_calls);
 }else if(!strcmp(argv[1],"migration_disconnect")){
  migration_begin();recovery_exit_zephyr_disconnected();
  command_group(MGMT_EVT_OP_CMD_DONE,0x8042,0,0);
  assert(!queued_exit&&!control.exiting&&!control.migration_pending&&!reboot_calls);
 }else if(!strcmp(argv[1],"migration_recheck")){
  migration_begin();command_group(MGMT_EVT_OP_CMD_DONE,0x8042,0,0);
  live_hash[0]^=1;queued_exit->handler(queued_exit);
  assert(!reboot_calls&&!control.exiting&&!control.migration_pending&&!clear_calls);
 }else if(!strcmp(argv[1],"migration_preflight")){
  migration_image=true;complete_retry();preflight_error=-EACCES;
  command_group(MGMT_EVT_OP_CMD_RECV,0x8042,0,MGMT_OP_WRITE);
  assert(recovery_exit_zephyr_migration_request(live_hash)==-EACCES);
  command_group(MGMT_EVT_OP_CMD_DONE,0x8042,0,11);
  assert(!control.exiting&&!queued_exit&&!reboot_calls);
 }else if(!strcmp(argv[1],"sdk_reset")||!strcmp(argv[1],"sdk_reset_fault")){
  command_group(MGMT_EVT_OP_CMD_RECV,0,5,MGMT_OP_WRITE);
  if(!strcmp(argv[1],"sdk_reset_fault"))verify_error=-EACCES;
  int rc=recovery_exit_zephyr_prepare_reset();
  if(verify_error)assert(rc==-EACCES&&!control.exiting);
  else{
   assert(!rc&&control.exiting&&!control.migration_pending&&clear_calls==1);
   command_group(MGMT_EVT_OP_CMD_DONE,0,5,5);recovery_exit_zephyr_disconnected();
   assert(control.exiting);mutation_refused();assert(!queued_exit&&!reboot_calls);
  }
 }else if(!strcmp(argv[1],"sdk_reset_migration")){
  migration_image=true;complete_retry();command_group(MGMT_EVT_OP_CMD_RECV,0,5,MGMT_OP_WRITE);
  assert(recovery_exit_zephyr_prepare_reset()==-EACCES&&!control.exiting&&!clear_calls);
 }else if(!strcmp(argv[1],"sdk_reset_partial")){
  begin_upload();done_upload(0);command_group(MGMT_EVT_OP_CMD_RECV,0,5,MGMT_OP_WRITE);
  assert(recovery_exit_zephyr_prepare_reset()==-EBUSY&&!control.exiting&&!clear_calls);
 }else if(!strcmp(argv[1],"admission_store_failure")){
  store_error=-EIO;
  struct mgmt_evt_op_cmd_arg arg={.group=MGMT_GROUP_ID_IMAGE,.id=IMG_MGMT_ID_UPLOAD,.op=MGMT_OP_WRITE};
  int32_t rc=0;uint16_t group=0;bool abort_more=false;
  assert(commands.callback(MGMT_EVT_OP_CMD_RECV,MGMT_CB_OK,&rc,&group,&abort_more,&arg,sizeof(arg))==MGMT_CB_ERROR_RC);
  assert(rc==MGMT_ERR_EBUSY&&abort_more&&control.partial&&!control.durable&&!marker_present);
  command(MGMT_EVT_OP_CMD_DONE,IMG_MGMT_ID_UPLOAD,10);
  assert(!control.command_busy&&!admitted_command);
  command_group(MGMT_EVT_OP_CMD_RECV,0x8041,0,MGMT_OP_READ);
  assert(control.command_busy&&admitted_command&&control.partial);
  command_group(MGMT_EVT_OP_CMD_DONE,0x8041,0,0);
  manual_attempt();assert(!reboot_calls&&control.partial);
  store_error=0;complete_retry();manual_attempt();assert(reboot_calls==1);
 }else assert(!"unknown scenario");
 assert(!gate.depth&&!image_lock_depth);
 printf("PASS %s\n",argv[1]);return 0;
}
