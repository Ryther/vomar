#include "vimar_power_protection.h"
#include "research_handoff.h"
#include <zephyr/drivers/retained_mem.h>
#include <errno.h>
#include <string.h>
#include <hal/nrf_gpio.h>
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/timer/nrf_rtc_timer.h>
#include <zephyr/settings/settings.h>

BUILD_ASSERT(IS_ENABLED(CONFIG_NRF_RTC_TIMER));

/* Opt-in shared adapter. CPU/flash/reset coverage still needs bench timing.
 * Timer ISR samples independently of ZBOSS and BLE/system work queues. No
 * settings, logs or radio operation executes under the GPIO/state spinlock. */
static struct candidate_power_protection state;
static struct k_spinlock lock;
static bool initialized,cancel_pending,storage_failed;
static uint8_t durable[CANDIDATE_PROTECTION_RECORD_SIZE];
static bool have_durable;
static struct k_work_q storage_queue;
static struct k_work_delayable store_work;
K_THREAD_STACK_DEFINE(storage_stack,2048);
K_MUTEX_DEFINE(store_mutex);
static const struct device *warm_marker=DEVICE_DT_GET(DT_NODELABEL(gpregret2));
static int warm_load(void *ctx,uint8_t *p,size_t n)
{ARG_UNUSED(ctx);ssize_t count=settings_load_one("vimar/handoff",p,n);return count==(ssize_t)n?0:(count<0?(int)count:-EINVAL);}
static int warm_get(void *ctx,uint8_t *p)
{ARG_UNUSED(ctx);return device_is_ready(warm_marker)?retained_mem_read(warm_marker,0,p,1):-ENODEV;}
static const struct research_handoff_io warm_io={.load=warm_load,.get_marker=warm_get};
static void store(struct k_work *);
static void sample(struct k_timer *);
K_TIMER_DEFINE(monitor,sample,NULL);

static void force_off(void)
{nrf_gpio_pin_clear(14);nrf_gpio_cfg_output(14);}
static bool blocked_locked(void)
{return !initialized||storage_failed||cancel_pending||candidate_power_protection_blocked(&state);}
static void encode_locked(uint8_t *p)
{
 struct candidate_power_protection copy=state;
 /* A trip not yet reconciled with the main controller must survive a reset
  * even if raw LOW has meanwhile cleared the signal's own inhibit. */
 if(cancel_pending)copy.inhibit=true;
 candidate_power_protection_encode(&copy,p);
}
static void poll_locked(void)
{
 bool was=candidate_power_protection_blocked(&state);
 /* Zephyr uptime in a timeout callback is its scheduled expiry, not the
  * physical sample time. Use the same extended hardware clock in all callers:
  * overdue timer callbacks must neither move time backwards nor hide stalls. */
 uint64_t now=k_cyc_to_ms_floor64(z_nrf_rtc_timer_read());
 unsigned events=candidate_power_protection_sample(&state,now,nrf_gpio_pin_read(31));
 if((events&CANDIDATE_PROTECTION_TRIP)||(!was&&candidate_power_protection_blocked(&state)))cancel_pending=true;
 if(blocked_locked())force_off();
}
static void schedule_store(void)
{(void)k_work_reschedule_for_queue(&storage_queue,&store_work,K_NO_WAIT);}
static void sample(struct k_timer *unused)
{
 ARG_UNUSED(unused);uint8_t record[CANDIDATE_PROTECTION_RECORD_SIZE];
 k_spinlock_key_t key=k_spin_lock(&lock);poll_locked();encode_locked(record);
 bool changed=!have_durable||memcmp(record,durable,sizeof(record));
 k_spin_unlock(&lock,key);
 if(changed&&!k_work_delayable_is_pending(&store_work))schedule_store();
}
int vimar_power_protection_flush(void)
{
 if(!initialized)return-EAGAIN;
 int rc=k_mutex_lock(&store_mutex,K_FOREVER);if(rc)return rc;
 uint8_t record[CANDIDATE_PROTECTION_RECORD_SIZE];
 k_spinlock_key_t key=k_spin_lock(&lock);encode_locked(record);
 bool changed=!have_durable||memcmp(record,durable,sizeof(record));k_spin_unlock(&lock,key);
 rc=changed?settings_save_one("vimar/p031",record,sizeof(record)):0;
 key=k_spin_lock(&lock);
 storage_failed=rc!=0;
 if(rc){cancel_pending=true;state.notification=true;}
 if(!rc){memcpy(durable,record,sizeof(record));have_durable=true;}
 if(blocked_locked())force_off();
 k_spin_unlock(&lock,key);k_mutex_unlock(&store_mutex);return rc;
}
static void store(struct k_work *unused)
{
 ARG_UNUSED(unused);
 if(vimar_power_protection_flush()!=0)
  (void)k_work_reschedule_for_queue(&storage_queue,&store_work,K_SECONDS(1));
}
int vimar_power_protection_init(void)
{
 if(initialized)return 0;
 const struct device *gpio=DEVICE_DT_GET(DT_NODELABEL(gpio0));
 int rc=device_is_ready(gpio)?gpio_pin_configure(gpio,31,GPIO_INPUT):-ENODEV;
 if(rc){force_off();return rc;}
 uint8_t record[CANDIDATE_PROTECTION_RECORD_SIZE];
 struct candidate_protection_record inherited={0};
 ssize_t n=settings_load_one("vimar/p031",record,sizeof(record));
 if(n!=0&&n!=-ENOENT){
  if(n<0||candidate_power_protection_decode(record,(size_t)n,&inherited))
   inherited=(struct candidate_protection_record){.inhibit=true,.input_fault=true,.notification=true};
  else {memcpy(durable,record,sizeof(record));have_durable=true;}
 }
 candidate_power_protection_init(&state,&inherited);
 cancel_pending=inherited.inhibit||inherited.input_fault||inherited.notification;
 initialized=true;
 k_work_queue_start(&storage_queue,storage_stack,K_THREAD_STACK_SIZEOF(storage_stack),4,NULL);
 k_work_init_delayable(&store_work,store);
 k_spinlock_key_t key=k_spin_lock(&lock);poll_locked();k_spin_unlock(&lock,key);
 /* Establish a durable checkpoint before permitting a newly initialized ON.
  * Peek does not consume the authorization needed by main after recovery. */
 struct research_protected_handoff warm;
 int warm_result=research_handoff_peek_protected(&warm_io,&warm);
 if(warm_result<0){state.inhibit=true;state.input_fault=true;state.notification=true;cancel_pending=true;force_off();}
 if(warm_result==1){
  if(warm.inhibited){state.inhibit=true;cancel_pending=true;force_off();}
  else if(warm.level!=-32768&&warm.trips==state.trips)
   vimar_power_protection_restore_armed(warm.armed);
 }
 rc=vimar_power_protection_flush();
 k_timer_start(&monitor,K_MSEC(CANDIDATE_PROTECTION_POLL_MS),K_MSEC(CANDIDATE_PROTECTION_POLL_MS));
 if(rc)schedule_store();
 return rc;
}
int vimar_power_protection_gate(bool on)
{
 k_spinlock_key_t key=k_spin_lock(&lock);
 if(initialized)poll_locked();
 bool blocked=blocked_locked();
 if(on&&!blocked)candidate_power_protection_acknowledge(&state);
 nrf_gpio_pin_write(14,on&&!blocked);
 k_spin_unlock(&lock,key);
 return on&&blocked?-EACCES:0;
}
bool vimar_power_protection_blocked(void)
{
 k_spinlock_key_t key=k_spin_lock(&lock);if(initialized)poll_locked();
 bool blocked=blocked_locked();k_spin_unlock(&lock,key);return blocked;
}
bool vimar_power_protection_cancel_pending(void)
{
 k_spinlock_key_t key=k_spin_lock(&lock);bool pending=cancel_pending;
 k_spin_unlock(&lock,key);return pending;
}
bool vimar_power_protection_status_blocked(void)
{
 k_spinlock_key_t key=k_spin_lock(&lock);bool blocked=blocked_locked();
 k_spin_unlock(&lock,key);return blocked;
}
void vimar_power_protection_cancel_acknowledged(void)
{
 k_spinlock_key_t key=k_spin_lock(&lock);cancel_pending=false;
 k_spin_unlock(&lock,key);schedule_store();
}
void vimar_power_protection_snapshot(struct candidate_power_protection *out)
{k_spinlock_key_t key=k_spin_lock(&lock);*out=state;k_spin_unlock(&lock,key);}
void vimar_power_protection_restore_armed(bool armed)
{
 if(!armed)return;
 k_spinlock_key_t key=k_spin_lock(&lock);
 /* A warm ON authorized after qualified LOW cannot ignore an already-HIGH
  * status at re-entry. Conservative immediate latch; cold HIGH is unchanged. */
 state.low_qualified=true;
 if(state.raw_high){if(state.trips<UINT32_MAX)state.trips++;state.inhibit=true;state.notification=true;cancel_pending=true;force_off();}
 k_spin_unlock(&lock,key);schedule_store();
}

void vimar_power_protection_latch_input_failure(void)
{
 k_spinlock_key_t key=k_spin_lock(&lock);
 state.inhibit=true;state.input_fault=true;state.notification=true;cancel_pending=true;
 force_off();bool can_store=initialized;k_spin_unlock(&lock,key);
 if(can_store)schedule_store();
}
