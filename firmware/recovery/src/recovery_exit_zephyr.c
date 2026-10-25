/* Local exit is serialized with actual MCUmgr command admission, not merely
 * connection state. Persistent intent survives disconnect/reset mid-upload. */
#include "recovery_exit_zephyr.h"
#include "recovery_migration_config.h"
#include "recovery_exit.h"
#include "recovery_exit_control.h"
#include "recovery_primary.h"
#if defined(CONFIG_VIMAR_RECOVERY_MIGRATION_EXEC)
#include "recovery_migration.h"
#include <string.h>
#endif
#include "vimar_power_protection.h"
#if defined(CONFIG_VIMAR_RECOVERY_SERVICE_MODE)
#include "recovery_session.h"
#include "vimar_led.h"
#endif
#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/mgmt/mcumgr/mgmt/callbacks.h>
#include <zephyr/mgmt/mcumgr/grp/img_mgmt/img_mgmt.h>
#include <mgmt/mcumgr/grp/img_mgmt/img_mgmt_priv.h>
#include <zephyr/retention/bootmode.h>
#include <zephyr/settings/settings.h>
#include <zephyr/sys/reboot.h>
#include <errno.h>
LOG_MODULE_REGISTER(recovery_exit,LOG_LEVEL_INF);
static const struct gpio_dt_spec buttons[]={
 GPIO_DT_SPEC_GET(DT_ALIAS(sw0),gpios),GPIO_DT_SPEC_GET(DT_ALIAS(sw1),gpios)
};
static struct recovery_exit gesture;
static struct recovery_exit_control control;
K_MUTEX_DEFINE(gate);
static struct k_work_q exit_queue;
K_THREAD_STACK_DEFINE(exit_stack,8192);
static struct k_work exit_work;
static struct k_work_delayable poll_work;
static bool buttons_ready,manual_exit_pending;
static bool admitted_command;
static uint16_t admitted_group;
static uint8_t admitted_id;
#if defined(CONFIG_VIMAR_RECOVERY_MIGRATION_EXEC)
static uint8_t migration_hash[32];
#endif
#if defined(CONFIG_VIMAR_RECOVERY_SERVICE_MODE)
static struct recovery_session session;
static uint64_t session_started;
static bool led_ready;
static bool session_due(void)
{
 return recovery_session_poll(&session,(uint64_t)k_uptime_get(),
  control.command_busy||control.session||control.exiting,control.partial);
}
#endif
static const char marker_key[]="vimar/recovery_upload";
static int persist(void *ctx,bool dirty)
{
 ARG_UNUSED(ctx);uint8_t value=1;
 return dirty?settings_save_one(marker_key,&value,sizeof(value)):settings_delete(marker_key);
}
static int verify(void *ctx)
{
 ARG_UNUSED(ctx);
 return recovery_primary_validate((const uint8_t *)RECOVERY_PRIMARY_BASE,RECOVERY_PRIMARY_CAPACITY);
}
static int flush(void *ctx){ARG_UNUSED(ctx);return vimar_power_protection_flush();}
static int clear_boot(void *ctx){ARG_UNUSED(ctx);return bootmode_clear();}
static void reboot(void *ctx){ARG_UNUSED(ctx);sys_reboot(SYS_REBOOT_COLD);}
static const struct recovery_exit_io io={
 .persist=persist,.verify=verify,.flush=flush,.clear_boot=clear_boot,.reboot=reboot
};
#if defined(CONFIG_VIMAR_RECOVERY_MIGRATION_EXEC)
static int verify_uploaded(void *ctx)
{
 ARG_UNUSED(ctx);
 return recovery_primary_validate_upload((const uint8_t *)RECOVERY_PRIMARY_BASE,RECOVERY_PRIMARY_CAPACITY);
}
static int verify_migration(void *ctx)
{
 int rc=recovery_primary_validate_migration((const uint8_t *)RECOVERY_PRIMARY_BASE,RECOVERY_PRIMARY_CAPACITY,ctx);
 return rc?rc:recovery_migration_preflight();
}
static const struct recovery_exit_io upload_io={
 .persist=persist,.verify=verify_uploaded,.flush=flush,.clear_boot=clear_boot,.reboot=reboot
};
static const struct recovery_exit_io migration_io={
 .context=migration_hash,.persist=persist,.verify=verify_migration,.flush=flush,.clear_boot=clear_boot,.reboot=reboot
};
int recovery_exit_zephyr_migration_request(const uint8_t expected_hash[32])
{
 if(!expected_hash)return-EINVAL;
 k_mutex_lock(&gate,K_FOREVER);
 int rc=-EBUSY;
 if(admitted_command&&admitted_group==VIMAR_MIGRATION_GROUP&&admitted_id==0&&
    control.command_busy&&!control.exiting&&!control.partial&&!control.session){
  memcpy(migration_hash,expected_hash,sizeof(migration_hash));
  img_mgmt_take_lock();rc=recovery_exit_migration_request(&control,&migration_io);img_mgmt_release_lock();
  if(!rc)manual_exit_pending=false;
  else memset(migration_hash,0,sizeof(migration_hash));
 }
 k_mutex_unlock(&gate);return rc;
}
#endif
int recovery_exit_zephyr_prepare_reset(void)
{
 k_mutex_lock(&gate,K_FOREVER);
 int rc=-EBUSY;
 if(admitted_command&&admitted_group==0&&admitted_id==5&&control.command_busy&&
    !control.exiting&&!control.partial&&!control.session){
  img_mgmt_take_lock();rc=recovery_exit_sdk_reset_prepare(&control,&io);img_mgmt_release_lock();
 }
 k_mutex_unlock(&gate);return rc;
}
static void exit_handler(struct k_work *work)
{
 ARG_UNUSED(work);k_mutex_lock(&gate,K_FOREVER);
#if defined(CONFIG_VIMAR_RECOVERY_MIGRATION_EXEC)
 if(control.migration_pending){
  if(control.migration_ready&&!control.command_busy&&!control.session&&!control.partial){
   img_mgmt_take_lock();int rc=recovery_exit_migration_attempt(&control,&migration_io);img_mgmt_release_lock();
   if(rc){
#if defined(CONFIG_VIMAR_RECOVERY_SERVICE_MODE)
    recovery_session_refuse_exit(&session);
#endif
    LOG_WRN("Explicit migration refused; recovery retained: %d",rc);
   }
  }
  k_mutex_unlock(&gate);return;
 }
#endif
 bool requested=manual_exit_pending;manual_exit_pending=false;
#if defined(CONFIG_VIMAR_RECOVERY_SERVICE_MODE)
 /* Recheck under command admission: a newer command can invalidate a queued
  * idle timeout before this worker gets the gate. */
 requested=session_due()||requested;
#endif
 /* Do not invert gate/image-lock order while an existing handler is running:
  * its PENDING/STOPPED callback already owns the SDK image mutex. */
 if(requested&&!control.command_busy&&!control.session&&!control.partial){
  img_mgmt_take_lock();
  int rc=recovery_exit_attempt(&control,&io);
  img_mgmt_release_lock();
  if(rc){
#if defined(CONFIG_VIMAR_RECOVERY_SERVICE_MODE)
   recovery_session_refuse_exit(&session);
#endif
   LOG_WRN("Return to main refused; recovery retained: %d",rc);
  }
 }
 k_mutex_unlock(&gate);
}
static void poll_handler(struct k_work *work)
{
 ARG_UNUSED(work);uint8_t pressed=0;bool failed=!buttons_ready;
 for(size_t i=0;buttons_ready&&i<ARRAY_SIZE(buttons);i++){
  int value=gpio_pin_get_dt(&buttons[i]);
  if(value<0)failed=true;else if(value)pressed|=BIT(i);
 }
 k_mutex_lock(&gate,K_FOREVER);
 bool fire=recovery_exit_tick(&gesture,k_uptime_get_32(),pressed,
  failed||control.partial||control.session||control.command_busy||control.exiting);
 if(fire)manual_exit_pending=true;
 bool requested=fire;
#if defined(CONFIG_VIMAR_RECOVERY_SERVICE_MODE)
 if(failed)recovery_session_refuse_exit(&session);
 requested=session_due()||requested;
 enum wireless_status_led_mode mode=recovery_session_led_mode(&session);
#endif
 k_mutex_unlock(&gate);
 if(requested)k_work_submit_to_queue(&exit_queue,&exit_work);
#if defined(CONFIG_VIMAR_RECOVERY_SERVICE_MODE)
 if(led_ready){
  uint64_t elapsed=(uint64_t)k_uptime_get()-session_started;
  struct led_output output=wireless_status_led_resolve(mode,
   vimar_power_protection_status_blocked(),NULL,elapsed);
  int error=vimar_led_render(&output,elapsed);
  if(error){led_ready=false;LOG_WRN("Recovery status LED unavailable: %d",error);}
 }
#endif
 k_work_reschedule(&poll_work,K_MSEC(20));
}
static enum mgmt_cb_return command_event(uint32_t event,enum mgmt_cb_return previous,
 int32_t *rc,uint16_t *group,bool *abort_more,void *data,size_t size)
{
 ARG_UNUSED(group);
 if(event==MGMT_EVT_OP_CMD_RECV&&previous!=MGMT_CB_OK)return previous;
 k_mutex_lock(&gate,K_FOREVER);
 int error=0;
 if(event==MGMT_EVT_OP_CMD_RECV){
  if(size!=sizeof(struct mgmt_evt_op_cmd_arg)||!data)error=-EINVAL;
  else{
   const struct mgmt_evt_op_cmd_arg *cmd=data;
   bool write=cmd->op==MGMT_OP_WRITE&&cmd->group==MGMT_GROUP_ID_IMAGE&&
    (cmd->id==IMG_MGMT_ID_UPLOAD||cmd->id==IMG_MGMT_ID_ERASE);
   error=recovery_exit_command_begin(&control,write,&io);
   if(!error){admitted_command=true;admitted_group=cmd->group;admitted_id=cmd->id;}
#if defined(CONFIG_VIMAR_RECOVERY_SERVICE_MODE)
   if(!error)recovery_session_activity(&session,(uint64_t)k_uptime_get());
#endif
  }
 }else if(event==MGMT_EVT_OP_CMD_DONE){
  const struct mgmt_evt_op_cmd_arg *done=data;
  /* Denied later commands also receive DONE. They cannot complete/cancel an
   * already accepted transition or release another command's busy state. */
  if(!admitted_command||!done||size!=sizeof(*done)||done->group!=admitted_group||done->id!=admitted_id){
   k_mutex_unlock(&gate);return previous;
  }
#if defined(CONFIG_VIMAR_RECOVERY_SERVICE_MODE)
  /* Decoder/handler failures can precede DFU_STARTED and DFU_STOPPED. Latch
   * recovery immediately: a fast successful retry must not hide the failure. */
  if(control.partial&&(!done||size!=sizeof(*done)||
   (done->err&&done->group==MGMT_GROUP_ID_IMAGE&&
    (done->id==IMG_MGMT_ID_UPLOAD||done->id==IMG_MGMT_ID_ERASE))))
   recovery_session_refuse_exit(&session);
#endif
  recovery_exit_command_done(&control);
  admitted_command=false;
#if defined(CONFIG_VIMAR_RECOVERY_MIGRATION_EXEC)
  if(done->group==VIMAR_MIGRATION_GROUP&&done->id==0){
   /* SDK smp_process_request_packet notifies successful DONE only after its
    * transport output returns; BT output waits for notification completion. */
   recovery_exit_migration_done(&control,done->err==0);
   if(control.migration_ready)k_work_submit_to_queue(&exit_queue,&exit_work);
  }
#endif
#if defined(CONFIG_VIMAR_RECOVERY_SERVICE_MODE)
  recovery_session_activity(&session,(uint64_t)k_uptime_get());
#endif
 }
 k_mutex_unlock(&gate);
 if(error){*rc=MGMT_ERR_EBUSY;*abort_more=true;return MGMT_CB_ERROR_RC;}
 return previous;
}
static enum mgmt_cb_return image_event(uint32_t event,enum mgmt_cb_return previous,
 int32_t *rc,uint16_t *group,bool *abort_more,void *data,size_t size)
{
 ARG_UNUSED(rc);ARG_UNUSED(group);ARG_UNUSED(abort_more);ARG_UNUSED(data);ARG_UNUSED(size);
 k_mutex_lock(&gate,K_FOREVER);
 if(event==MGMT_EVT_OP_IMG_MGMT_DFU_STARTED)recovery_exit_transfer_started(&control);
 else if(event==MGMT_EVT_OP_IMG_MGMT_DFU_STOPPED){
  recovery_exit_transfer_stopped(&control);
#if defined(CONFIG_VIMAR_RECOVERY_SERVICE_MODE)
  recovery_session_refuse_exit(&session);
#endif
 }
 else if(event==MGMT_EVT_OP_IMG_MGMT_DFU_PENDING){
#if defined(CONFIG_VIMAR_RECOVERY_MIGRATION_EXEC)
  int error=recovery_exit_transfer_complete(&control,&upload_io);
#else
  int error=recovery_exit_transfer_complete(&control,&io);
#endif
  if(error)LOG_WRN("Uploaded image remains in recovery: %d",error);
#if defined(CONFIG_VIMAR_RECOVERY_SERVICE_MODE)
  if(error)recovery_session_refuse_exit(&session);
  else recovery_session_activity(&session,(uint64_t)k_uptime_get());
#endif
 }
 k_mutex_unlock(&gate);
 return previous;
}
static struct mgmt_callback commands={.callback=command_event,
 .event_id=MGMT_EVT_OP_CMD_RECV|MGMT_EVT_OP_CMD_DONE};
static struct mgmt_callback images={.callback=image_event,
 .event_id=MGMT_EVT_OP_IMG_MGMT_DFU_STARTED|MGMT_EVT_OP_IMG_MGMT_DFU_STOPPED|MGMT_EVT_OP_IMG_MGMT_DFU_PENDING};
void recovery_exit_zephyr_disconnected(void)
{
 k_mutex_lock(&gate,K_FOREVER);
#if defined(CONFIG_VIMAR_RECOVERY_MIGRATION_EXEC)
 recovery_exit_migration_cancel(&control);
#endif
 /* The SDK does not emit DFU_STOPPED for every BT disconnect. Preserve the
  * durable partial intent and any command still executing on its workqueue. */
 if(control.partial||control.session){
  recovery_exit_transfer_stopped(&control);
#if defined(CONFIG_VIMAR_RECOVERY_SERVICE_MODE)
  recovery_session_refuse_exit(&session);
#endif
 }
 k_mutex_unlock(&gate);
}
void recovery_exit_zephyr_init(int settings_error,bool trusted_entry)
{
 uint8_t value=0;
 ssize_t length=settings_error?settings_error:settings_load_one(marker_key,&value,sizeof(value));
 recovery_exit_control_init(&control,length,value);
 recovery_exit_init(&gesture);
#if defined(CONFIG_VIMAR_RECOVERY_SERVICE_MODE)
 struct boot_trace_entry entry;vimar_boot_trace_snapshot(&entry);
 session_started=(uint64_t)k_uptime_get();
 recovery_session_init(&session,(enum boot_reason)entry.reason,
  trusted_entry&&!settings_error,control.partial,session_started);
 led_ready=vimar_led_init()==0;
 if(!led_ready)LOG_WRN("Recovery status LED initialization failed");
#else
 ARG_UNUSED(trusted_entry);
#endif
 mgmt_callback_register(&commands);mgmt_callback_register(&images);
 buttons_ready=true;
 for(size_t i=0;i<ARRAY_SIZE(buttons);i++){
  if(!gpio_is_ready_dt(&buttons[i])||gpio_pin_configure_dt(&buttons[i],GPIO_INPUT)){
   LOG_ERR("Local exit buttons unavailable; BLE recovery retained");buttons_ready=false;break;
  }
 }
 k_work_init(&exit_work,exit_handler);
 k_work_queue_start(&exit_queue,exit_stack,K_THREAD_STACK_SIZEOF(exit_stack),5,NULL);
 k_work_init_delayable(&poll_work,poll_handler);
 k_work_schedule(&poll_work,K_MSEC(20));
}
