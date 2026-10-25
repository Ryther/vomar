"""Exercise the real shared adapter with deterministic GPIO/settings/kernel IO."""
from pathlib import Path
import subprocess,tempfile,unittest
R=Path(__file__).resolve().parents[3]
class AdapterTests(unittest.TestCase):
 def test_guard_startup_persistence_and_warm_handoff_failures(self):
  with tempfile.TemporaryDirectory() as tmp:
   d=Path(tmp)
   files={
    'env.h':'''#ifndef FAKE_ENV_H
#define FAKE_ENV_H
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <sys/types.h>
extern uint64_t fake_now,fake_rtc_ms;extern int raw,gate,config_error,save_error,load_error,marker_error;
extern uint8_t saved[16],marker;extern size_t saved_n;
struct device {int unused;};extern const struct device fake_device;
struct k_timer {void(*handler)(struct k_timer*);};extern struct k_timer *active_timer;
#endif
''',
    'zephyr/kernel.h':'''#include "env.h"
#define ARG_UNUSED(x) ((void)(x))
#define IS_ENABLED(x) (x)
#define BUILD_ASSERT(x) _Static_assert(x,#x)
#define K_THREAD_STACK_DEFINE(n,s) char n[s]
#define K_THREAD_STACK_SIZEOF(n) sizeof(n)
#define K_FOREVER (-1)
#define K_NO_WAIT 0
#define K_MSEC(n) (n)
#define K_SECONDS(n) ((n)*1000)
struct k_spinlock {int unused;};typedef int k_spinlock_key_t;
struct k_mutex {int unused;};
#define K_MUTEX_DEFINE(n) struct k_mutex n
struct k_work {int unused;};struct k_work_q {int unused;};
struct k_work_delayable {struct k_work work;bool pending;void(*handler)(struct k_work*);};
#define K_TIMER_DEFINE(n,f,s) struct k_timer n={.handler=f}
static inline int k_spin_lock(struct k_spinlock*p){(void)p;return 0;}
static inline void k_spin_unlock(struct k_spinlock*p,int k){(void)p;(void)k;}
static inline int k_mutex_lock(struct k_mutex*p,int t){(void)p;(void)t;return 0;}
static inline void k_mutex_unlock(struct k_mutex*p){(void)p;}
static inline uint64_t k_uptime_get(void){return fake_now;}
static inline uint64_t k_cyc_to_ms_floor64(uint64_t cycles){return cycles;}
static inline void k_work_queue_start(struct k_work_q*q,void*s,size_t n,int p,void*c){(void)q;(void)s;(void)n;(void)p;(void)c;}
static inline void k_work_init_delayable(struct k_work_delayable*w,void(*f)(struct k_work*)){w->handler=f;}
static inline int k_work_reschedule_for_queue(struct k_work_q*q,struct k_work_delayable*w,int t){(void)q;(void)t;w->pending=true;return 0;}
static inline bool k_work_delayable_is_pending(struct k_work_delayable*w){return w->pending;}
static inline void k_timer_start(struct k_timer*t,int a,int b){(void)a;(void)b;active_timer=t;}
''',
    'zephyr/drivers/timer/nrf_rtc_timer.h':'''#include "env.h"
static inline uint64_t z_nrf_rtc_timer_read(void){return fake_rtc_ms;}
''',
    'zephyr/drivers/gpio.h':'''#include "env.h"
#define DT_NODELABEL(n) 0
#define DEVICE_DT_GET(n) (&fake_device)
#define GPIO_INPUT 0
static inline bool device_is_ready(const struct device*d){(void)d;return true;}
static inline int gpio_pin_configure(const struct device*d,int p,int f){(void)d;(void)f;return p==31?config_error:-1;}
''',
    'hal/nrf_gpio.h':'''#include "env.h"
static inline int nrf_gpio_pin_read(unsigned p){return p==31?raw:1;}
static inline void nrf_gpio_pin_clear(unsigned p){if(p==14)gate=0;}
static inline void nrf_gpio_cfg_output(unsigned p){(void)p;}
static inline void nrf_gpio_pin_write(unsigned p,unsigned v){if(p==14)gate=v;}
''',
    'zephyr/settings/settings.h':'''#include "env.h"
ssize_t settings_load_one(const char*,void*,size_t);
int settings_save_one(const char*,const void*,size_t);
''',
    'zephyr/drivers/retained_mem.h':'''#include "env.h"
int retained_mem_read(const struct device*,size_t,void*,size_t);
''',
   }
   for name,source in files.items():
    p=d/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(source)
   (d/'test.c').write_text('''#include "env.h"
#include "vimar_power_protection.h"
#include "research_handoff.h"
#include <assert.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
uint64_t fake_now,fake_rtc_ms;int raw=1,gate=1,config_error,save_error,load_error,marker_error;
uint8_t saved[16],marker;size_t saved_n;const struct device fake_device={0};struct k_timer *active_timer;
ssize_t settings_load_one(const char*k,void*p,size_t n){if(!strcmp(k,"vimar/handoff"))return-EIO;if(load_error)return load_error;if(saved_n){memcpy(p,saved,n<saved_n?n:saved_n);return saved_n;}return 0;}
int settings_save_one(const char*k,const void*p,size_t n){assert(!strcmp(k,"vimar/p031")&&n==16);if(save_error)return save_error;memcpy(saved,p,n);saved_n=n;return 0;}
int retained_mem_read(const struct device*d,size_t o,void*p,size_t n){(void)d;(void)o;assert(n==1);if(marker_error)return marker_error;*(uint8_t*)p=marker;return 0;}
static void ticks(uint64_t a,uint64_t b,int level){raw=level;for(fake_now=a;fake_now<=b;fake_now+=10){fake_rtc_ms=fake_now;active_timer->handler(active_timer);}fake_now=fake_rtc_ms=b;}
int main(int argc,char**argv){
 assert(argc==2);int scenario=atoi(argv[1]);
 if(scenario==1){
  assert(vimar_power_protection_init()==0&&gate==1);assert(vimar_power_protection_gate(true)==0);
  ticks(10,590,0);ticks(600,680,1);assert(gate==0&&vimar_power_protection_cancel_pending());
  assert(vimar_power_protection_flush()==0);
  ticks(690,1270,0);assert(vimar_power_protection_blocked());
  assert(vimar_power_protection_gate(true)==-EACCES&&gate==0);
  /* Caller has committed controller OFF before acknowledging this cancellation. */
  vimar_power_protection_cancel_acknowledged();assert(!vimar_power_protection_blocked());
  assert(vimar_power_protection_flush()==0);
  struct candidate_protection_record record;assert(candidate_power_protection_decode(saved,16,&record)==0&&record.notification);
  assert(vimar_power_protection_gate(true)==0&&gate==1);
 }else if(scenario==2){
  struct candidate_power_protection old;candidate_power_protection_init(&old,0);old.notification=true;
  candidate_power_protection_encode(&old,saved);saved_n=16;
  assert(vimar_power_protection_init()==0&&gate==0&&vimar_power_protection_cancel_pending());
  assert(vimar_power_protection_gate(true)==-EACCES);
 }else if(scenario==3){marker=RESEARCH_PROTECTED_HANDOFF_MARKER;assert(vimar_power_protection_init()==0);assert(gate==0&&vimar_power_protection_blocked());}
 else if(scenario==4){load_error=-EIO;assert(vimar_power_protection_init()==0);assert(gate==0&&vimar_power_protection_blocked());}
 else if(scenario==5){save_error=-EIO;assert(vimar_power_protection_init()==-EIO&&gate==0);save_error=0;assert(vimar_power_protection_flush()==0);assert(vimar_power_protection_blocked());struct candidate_power_protection s;vimar_power_protection_snapshot(&s);assert(s.notification);}
 else if(scenario==6){config_error=-EIO;assert(vimar_power_protection_init()==-EIO&&gate==0);assert(vimar_power_protection_gate(true)==-EACCES);}
 else if(scenario==7){assert(vimar_power_protection_init()==0&&gate==1);vimar_power_protection_latch_input_failure();assert(gate==0&&vimar_power_protection_blocked());}
 else if(scenario==8){
  raw=0;fake_now=fake_rtc_ms=1000;assert(vimar_power_protection_init()==0);
  fake_now=fake_rtc_ms=1035;assert(vimar_power_protection_gate(true)==0&&gate==1);
  /* A delayed Zephyr timeout reports its scheduled time, earlier than the
   * previous thread sample. Hardware RTC remains monotonic. */
  fake_now=1020;fake_rtc_ms=1040;active_timer->handler(active_timer);
  struct candidate_power_protection state;vimar_power_protection_snapshot(&state);
  assert(!state.input_fault&&state.max_gap_ms==35&&state.last_sample_ms==1040&&gate==1);
 }
 else if(scenario==9){
  raw=0;fake_now=fake_rtc_ms=1000;assert(vimar_power_protection_init()==0);
  assert(vimar_power_protection_gate(true)==0&&gate==1);
  /* A real250ms IRQ stall cannot be concealed by replayed30ms deadlines. */
  fake_now=1030;fake_rtc_ms=1250;active_timer->handler(active_timer);
  struct candidate_power_protection state;vimar_power_protection_snapshot(&state);
  assert(state.input_fault&&state.max_gap_ms==250&&gate==0);
  for(unsigned i=1;i<=25;i++){fake_now=1030+30*i;fake_rtc_ms=1250+i;active_timer->handler(active_timer);}
  vimar_power_protection_snapshot(&state);assert(state.input_fault&&!state.low_qualified&&gate==0);
 }
 else if(scenario==10){
  raw=0;fake_now=0;fake_rtc_ms=(UINT64_C(1)<<32)+100;
  assert(vimar_power_protection_init()==0);fake_rtc_ms+=30;active_timer->handler(active_timer);
  struct candidate_power_protection state;vimar_power_protection_snapshot(&state);
  assert(state.last_sample_ms==(UINT64_C(1)<<32)+130&&state.max_gap_ms==30&&!state.input_fault);
 }
 else if(scenario==11){
  assert(vimar_power_protection_status_blocked());
  assert(vimar_power_protection_init()==0&&gate==1);
  struct candidate_power_protection before,after;
  vimar_power_protection_snapshot(&before);
  /* A display read must not sample a changed GPIO/clock, trigger protection,
   * acknowledge a trip, persist data, or change output behind the monitor. */
  raw=0;fake_now=fake_rtc_ms=100000;
  assert(!vimar_power_protection_status_blocked()&&gate==1);
  vimar_power_protection_snapshot(&after);
  assert(!memcmp(&before,&after,sizeof(before)));
  active_timer->handler(active_timer);
  assert(vimar_power_protection_status_blocked()&&gate==0);
 }
 else if(scenario==12){
  save_error=-EIO;assert(vimar_power_protection_init()==-EIO);
  assert(vimar_power_protection_status_blocked());
  save_error=0;assert(!vimar_power_protection_flush());
  assert(vimar_power_protection_status_blocked());
 }
 return 0;
}
''')
   exe=str(d/'adapter')
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-DCONFIG_VIMAR_P031_PROTECTION=1','-DCONFIG_NRF_RTC_TIMER=1','-I',str(d),'-I',str(R/'firmware/src'),'-I',str(R/'firmware/research/src'),str(d/'test.c'),str(R/'firmware/src/vimar_power_protection.c'),str(R/'firmware/src/candidate_power_protection.c'),str(R/'firmware/research/src/research_handoff.c'),'-o',exe],check=True)
   for scenario in range(1,13):
    with self.subTest(scenario=scenario):subprocess.run([exe,str(scenario)],check=True)
