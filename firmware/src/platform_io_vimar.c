#include "platform_io.h"
#include "vimar_level.h"
#include "vimar_buttons.h"
#include "vimar_attachment_gpio.h"
#include "vimar_led.h"
#include "research_output.h"
#include "research_handoff.h"
#include "vimar_power_protection.h"
#include "boot_trace.h"
#include "zigbee_device.h"
#include "connection_intent.h"
#include <errno.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/retained_mem.h>
#include <zephyr/retention/bootmode.h>
#include <zephyr/settings/settings.h>
#include <zephyr/sys/reboot.h>
#include <zephyr/logging/log.h>
LOG_MODULE_REGISTER(vimar_io,LOG_LEVEL_INF);
static const struct gpio_dt_spec up=GPIO_DT_SPEC_GET(DT_ALIAS(sw0),gpios);
static const struct gpio_dt_spec down=GPIO_DT_SPEC_GET(DT_ALIAS(sw1),gpios);
static const struct device *marker=DEVICE_DT_GET(DT_NODELABEL(gpregret2));
static struct vimar_buttons buttons;
static bool have_handoff,ready,failed,recovering,input_valid;
static int32_t handoff_raw,last_raw=-32768;
static int load(void *ctx,uint8_t *p,size_t n){ARG_UNUSED(ctx);ssize_t count=settings_load_one("vimar/handoff",p,n);return count==(ssize_t)n?0:(count<0?(int)count:-EINVAL);}
static int save(void *ctx,const uint8_t *p,size_t n){ARG_UNUSED(ctx);return settings_save_one("vimar/handoff",p,n);}
static int get(void *ctx,uint8_t *p){ARG_UNUSED(ctx);return retained_mem_read(marker,0,p,1);}
static int set(void *ctx,uint8_t n){ARG_UNUSED(ctx);return retained_mem_write(marker,0,&n,1);}
static const struct research_handoff_io io={.load=load,.save=save,.get_marker=get,.set_marker=set};
const struct dimmer_secondary_capabilities *platform_io_capabilities(void)
{
 /* An nRF DMA completion is not acknowledgement/physical feedback from power stage. */
 static const struct dimmer_secondary_capabilities caps={.acceptance_feedback=false,.physical_feedback=false,.stock_switch_mode=false};return &caps;
}
int platform_io_restore(bool *on,uint8_t *level)
{
 if(!device_is_ready(marker))return-ENODEV;
 int result;
#if defined(CONFIG_VIMAR_P031_PROTECTION)
 struct research_protected_handoff h;
 result=research_handoff_take_protected(&io,&h);
 struct candidate_power_protection protection;
 vimar_power_protection_snapshot(&protection);
 if(result<0){*on=false;return result;}
 if(result==1){
  handoff_raw=h.level;
  if(h.inhibited||vimar_power_protection_blocked()||h.trips!=protection.trips)handoff_raw=-32768;
 }
#else
 result=research_handoff_take(&io,&handoff_raw);
#endif
 have_handoff=result==1;
 if(have_handoff&&!vimar_level_decode(handoff_raw,on,level)){have_handoff=false;return-EINVAL;}
 return result;
}
int platform_io_init(bool on,uint8_t level)
{
 int32_t raw;if(!vimar_level_encode(on,level,&raw))return-EINVAL;
 if(have_handoff)raw=handoff_raw; /* Preserve exact signed value across BLE->Zigbee migration. */
 int error;
 if(!gpio_is_ready_dt(&up)||!gpio_is_ready_dt(&down))return-ENODEV;
 error=gpio_pin_configure_dt(&up,GPIO_INPUT);if(error)return error;
 error=gpio_pin_configure_dt(&down,GPIO_INPUT);if(error)return error;
 int attachment_error=vimar_attachment_gpio_init();
 if(attachment_error)LOG_WRN("Wired input init:%d",attachment_error);
 ready=true;input_valid=true; /* Keep recovery input usable after an output failure. */
 if(vimar_power_protection_blocked())raw=-32768;
 error=research_output_init_at_level(raw);
 failed=error!=0;last_raw=failed?-32768:raw;
 if(error)return error;
 int led_error=vimar_led_init();if(led_error)LOG_WRN("LED init:%d",led_error);
 return 0;
}
int platform_io_apply(bool on,uint8_t level)
{
 if(!ready||failed)return-EIO;
 if(recovering)return-EBUSY;
 int32_t raw;if(!vimar_level_encode(on,level,&raw))return-EINVAL;
 int error=research_output_level(raw);
 if(error){if(error!=-EACCES)failed=true;last_raw=-32768;}else{last_raw=raw;}
 if(on&&vimar_power_protection_blocked()){last_raw=-32768;return-EACCES;}
 return error;
}
void platform_io_render(bool on){ARG_UNUSED(on);}
void platform_io_led(const struct led_output *o,uint64_t now)
{
 static bool logged;int error=vimar_led_render(o,now);if(error&&!logged){LOG_WRN("LED render:%d",error);logged=true;}
}
void platform_io_tick(uint64_t now)
{
 if(!ready||recovering)return;
 int u=gpio_pin_get_dt(&up),d=gpio_pin_get_dt(&down);
 if(u<0||d<0){
  input_valid=false;zigbee_device_cancel_gestures();buttons.blocked=true;
  vimar_attachment_gpio_tick(now,true);
  buttons.enabled=false;buttons.chord=false;buttons.selecting=false;
  zigbee_device_connection_selector(false,now);return;
 }
 input_valid=true;
 bool was_selecting=buttons.selecting;
 struct vimar_button_sample sample=vimar_buttons_tick(&buttons,now,(u?1:0)|(d?2:0));
 if(sample.cancel)zigbee_device_cancel_gestures();
 vimar_attachment_gpio_tick(now,buttons.blocked||buttons.selecting||vimar_power_protection_blocked());
 if(sample.selector)zigbee_device_connection_selector(true,now);
 if(was_selecting&&!buttons.selecting)zigbee_device_connection_selector(false,now);
 if(sample.pairing){(void)platform_io_request_pairing();return;}
 if(sample.recovery){(void)vimar_boot_trace_request(BOOT_REASON_CHORD);(void)platform_io_request_recovery();return;}
 if(sample.changed&sample.pressed)zigbee_device_cancel_attachment();
 if(sample.changed&1)zigbee_device_local_edge_at((sample.pressed&1)?2:0,buttons.raw_since);
 if(sample.changed&2)zigbee_device_local_edge_at(1|((sample.pressed&2)?2:0),buttons.raw_since);
}

bool platform_io_input_settled(void)
{return input_valid&&!buttons.blocked&&buttons.raw==buttons.stable;}

static int request_connection(bool bluetooth)
{
 if(recovering)return-EBUSY;
 recovering=true;zigbee_device_cancel_gestures();
 int error=zigbee_device_prepare_recovery();
 if(vimar_power_protection_blocked())last_raw=-32768;
#if defined(CONFIG_VIMAR_P031_PROTECTION)
 struct candidate_power_protection protection;vimar_power_protection_snapshot(&protection);
 struct research_protected_handoff h={.level=last_raw,.trips=protection.trips,
  .armed=protection.low_qualified,.inhibited=vimar_power_protection_blocked()};
 if(!error)error=research_handoff_prepare_protected(&io,&h);
#else
 if(!error)error=research_handoff_prepare(&io,last_raw);
#endif
 if(!error)error=vimar_power_protection_flush();
 if(!error)error=bluetooth?bootmode_set(BOOT_MODE_TYPE_BOOTLOADER):bootmode_clear();
 /* Persist the explicit network replacement last, immediately before reboot.
  * Initialisation/inspection never creates this intent. */
 if(!error&&!bluetooth)error=connection_intent_request();
 if(error){
#if defined(CONFIG_VIMAR_P031_PROTECTION)
 (void)vimar_boot_trace_request(BOOT_REASON_NONE);
#endif
 (void)set(NULL,0);recovering=false;LOG_ERR("Recovery request:%d",error);return error;}
 sys_reboot(SYS_REBOOT_COLD);return 0;
}
int platform_io_request_recovery(void){return request_connection(true);}
int platform_io_request_pairing(void){return request_connection(false);}

void platform_io_cancel_attachment(void){vimar_attachment_gpio_cancel();}
