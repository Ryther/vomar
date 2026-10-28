from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[3]
class ResearchOutputTests(unittest.TestCase):
 def test_restore_on_has_no_off_gate_pulse_and_timeout_disables_gate(self):
  with tempfile.TemporaryDirectory() as directory:
   d=Path(directory);(d/'hal').mkdir();(d/'zephyr').mkdir()
   (d/'hal/nrf_gpio.h').write_text('''#include <stdint.h>
uint32_t nrf_gpio_pin_out_read(uint32_t);void nrf_gpio_pin_clear(uint32_t);void nrf_gpio_cfg_output(uint32_t);void nrf_gpio_pin_write(uint32_t,uint32_t);
''')
   (d/'zephyr/kernel.h').write_text('''#define __aligned(n) __attribute__((aligned(n)))
#define __DMB() ((void)0)
static inline void k_busy_wait(unsigned n){(void)n;}
''')
   (d/'hal/nrf_pwm.h').write_text('''#include <stdint.h>
#include <stdbool.h>
#define NRF_PWM1 ((void*)1)
#define NRF_PWM_PIN_NOT_CONNECTED UINT32_MAX
#define NRF_PWM_CLK_8MHz 1
#define NRF_PWM_MODE_UP 0
#define NRF_PWM_LOAD_INDIVIDUAL 2
#define NRF_PWM_STEP_AUTO 0
#define NRF_PWM_EVENT_SEQEND1 1
#define NRF_PWM_TASK_SEQSTART1 1
typedef struct{union{uint16_t*p_raw;}values;uint16_t length;uint32_t repeats,end_delay;}nrf_pwm_sequence_t;
void nrf_pwm_disable(void*);void nrf_pwm_enable(void*);void nrf_pwm_pins_set(void*,const uint32_t*);
void nrf_pwm_configure(void*,int,int,int);void nrf_pwm_decoder_set(void*,int,int);
void nrf_pwm_shorts_set(void*,unsigned);void nrf_pwm_int_set(void*,unsigned);
void nrf_pwm_sequence_set(void*,unsigned,const nrf_pwm_sequence_t*);
void nrf_pwm_loop_set(void*,unsigned);void nrf_pwm_event_clear(void*,int);
void nrf_pwm_task_trigger(void*,int);bool nrf_pwm_event_check(void*,int);
''')
   (d/'test.c').write_text('''#include "research_output.h"
#include "research_protocol.h"
#include <hal/nrf_pwm.h>
#include <hal/nrf_gpio.h>
#include <assert.h>
#include <errno.h>
static unsigned gate,off_writes,triggers,compare,phase,unsafe_phase_changes;static int timeout;
#if defined(CONFIG_VIMAR_P031_PROTECTION)
#include "vimar_power_protection.h"
static bool inhibit;
int vimar_power_protection_gate(bool on){nrf_gpio_pin_write(14,on&&!inhibit);return on&&inhibit?-EACCES:0;}
#endif
void nrf_gpio_pin_clear(uint32_t p){if(p==14){gate=0;off_writes++;}if(p==19){if(gate&&phase)unsafe_phase_changes++;phase=0;}}
uint32_t nrf_gpio_pin_out_read(uint32_t p){return p==14?gate:phase;}
void nrf_gpio_cfg_output(uint32_t p){(void)p;}
void nrf_gpio_pin_write(uint32_t p,uint32_t v){if(p==14){gate=v;if(!v)off_writes++;}if(p==19){if(gate&&phase!=v)unsafe_phase_changes++;phase=v;}}
void nrf_pwm_disable(void*p){(void)p;}void nrf_pwm_enable(void*p){(void)p;}
void nrf_pwm_pins_set(void*p,const uint32_t*v){(void)p;assert(v[0]==UINT32_MAX&&v[3]==13);}
void nrf_pwm_configure(void*p,int c,int m,int t){(void)p;assert(c==1&&m==0&&t==1024);}
void nrf_pwm_decoder_set(void*p,int l,int s){(void)p;assert(l==2&&s==0);}
void nrf_pwm_shorts_set(void*p,unsigned v){(void)p;(void)v;}void nrf_pwm_int_set(void*p,unsigned v){(void)p;(void)v;}
void nrf_pwm_sequence_set(void*p,unsigned i,const nrf_pwm_sequence_t*s){(void)p;(void)i;assert(s->length==4);compare=s->values.p_raw[3];}
void nrf_pwm_loop_set(void*p,unsigned n){(void)p;assert(n==1);}void nrf_pwm_event_clear(void*p,int e){(void)p;(void)e;}
void nrf_pwm_task_trigger(void*p,int t){(void)p;(void)t;triggers++;}
bool nrf_pwm_event_check(void*p,int e){(void)p;(void)e;return !timeout;}
int main(void){
 assert(research_output_init_at_level(0)==0);assert(gate==1&&compare==512&&triggers==1&&off_writes==0);
 assert(research_output_init_at_level(-16384)==0);assert(gate==1&&compare==768&&off_writes==0);
 assert(research_output_init_at_level(32767)==0);assert(gate==1&&compare==0&&off_writes==0);
 assert(research_output_init()==0);assert(gate==0&&compare==1024);
 timeout=1;assert(research_output_init_at_level(0)==-ETIMEDOUT&&gate==0);
 unsigned before=triggers;assert(research_output_init_at_level(32768)==-EINVAL&&triggers==before);
#if defined(CONFIG_VIMAR_P031_PROTECTION)
 timeout=0;inhibit=true;before=triggers;
 assert(research_output_init_at_level(0)==-EACCES&&gate==0&&triggers==before);
 assert(research_output_level(32767)==-EACCES&&gate==0&&triggers==before);
 assert(research_output_level(-32768)==0&&gate==0);
 inhibit=false;assert(research_output_level(0)==0&&gate==1);
#endif
 timeout=0;
 assert(research_output_init_at_level_phase(-32768,1)==0);
 assert(research_output_init_at_level_phase(0,1)==0&&phase==1);
 unsigned prior_off=off_writes;
 assert(research_output_init_at_level_phase(0,1)==0&&off_writes==prior_off);
 assert(research_output_set_phase_cut(0)==-EBUSY&&phase==1&&gate==1);
 assert(research_output_init_at_level_phase(0,0)==-EBUSY&&phase==1&&gate==1);
 assert(research_output_level(-32768)==0);
 assert(research_output_set_phase_cut(0)==0&&phase==0);
 assert(research_output_init_at_level_phase(0,0)==0&&gate==1&&phase==0);
 prior_off=off_writes;
 assert(research_output_init_at_level_phase(0,0)==0&&off_writes==prior_off&&phase==0);
 assert(research_output_init_at_level_phase(-32768,1)==0&&gate==0&&phase==1);
 assert(research_output_set_phase_cut(2)==-EINVAL);
 assert(research_output_init_at_level_phase(0,2)==-EINVAL);
 assert(unsafe_phase_changes==0);
 return 0;
}
''')
   # Compile the real adapter entry points with only Zephyr boundaries replaced.
   platform=(ROOT/'firmware/src/platform_io_vimar.c').read_text()
   init=platform[platform.index('int platform_io_init('):platform.index('int platform_io_check_phase_cut(')]
   apply=platform[platform.index('int platform_io_apply('):platform.index('void platform_io_render(')]
   zigbee=(ROOT/'firmware/src/zigbee_device.c').read_text()
   start=zigbee.index('    if (error != 0) {',zigbee.index('int zigbee_device_start('))
   failure=zigbee[start:zigbee.index('    if(unsupported)',start)]
   startup='static void startup_failure(int error){\n'+failure+'}\n'
   glue=r'''
#include "settings_record.h"
#include "vimar_level.h"
#include "application_controller.h"
static struct application_controller controller;
static bool have_handoff,ready,failed,recovering,input_valid,startup_inhibited;
static int32_t handoff_raw,last_raw=-32768;
static enum dimmer_phase_cut_mode phase_cut;
static int up,down,gpio_error;
#define LOG_ERR(message,error) ((void)(error))
#define GPIO_INPUT 0
#define LOG_WRN(...) ((void)0)
static bool gpio_is_ready_dt(const int *pin){(void)pin;return true;}
static int gpio_pin_configure_dt(const int *pin,int flags){(void)pin;(void)flags;return gpio_error;}
static int vimar_attachment_gpio_init(void){return 0;}
bool vimar_power_protection_blocked(void){return false;}
static int vimar_led_init(void){return 0;}
ACTUAL_PLATFORM_FUNCTIONS
ACTUAL_STARTUP_FAILURE
static void legacy_warm_handoff(void){
 const uint8_t old[]={0x56,0x4d,0x53,0x31,0x04,0x00,0x46,0x00,0x96,0x00,0xfa,0x00,0x64,0x00,0x0a,0x01,0x00,0x00,0x04,0x04,0x58,0x02,0x00,0x00,0x00,0x58,0x02,0x00,0x00,0x00,0x02,0xfe,0x0a,0x00,0x00,0x00,0xfe,0x00,0xff,0x00,0x0a,0x00,0x00,0x4d,0x0a,0x00,0x00,0x64,0x01,0x58,0x39,0x30,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x0a,0xf0,0x58,0x02,0x00,0x00,0x58,0x02,0x00,0x00,0x58,0x02,0x00,0x00,0x00,0x00,0xbc,0xbc,0x30,0xe4};
 struct dimmer_config config;bool on;uint8_t level;
 assert(settings_record_decode(old,sizeof(old),&config,&on,&level)==SETTINGS_RECORD_OK);
 assert(on&&level==88);
 phase_cut=config.phase_cut_mode;
 assert(vimar_level_encode(on,level,&handoff_raw));have_handoff=true;
 gate=1;phase=1;unsigned before=off_writes;
 const struct application_callbacks callbacks={0};
 application_controller_init(&controller,&config,on,level,&callbacks,NULL,0);
 application_controller_restore_handoff(&controller,on,level);
 int error=platform_io_init(on,level);
 startup_failure(error);
 if(phase_cut==DIMMER_PHASE_TRAILING_EDGE){
  assert(error==-EBUSY&&failed&&gate==0&&phase==1&&last_raw==-32768);
  assert(!controller.model.state.on&&!controller.model.state.target_on&&!controller.output_on&&!controller.output_pending);
  assert(controller.model.state.fault.active&&controller.model.state.fault.code==DIMMER_FAULT_SECONDARY_UNAVAILABLE);
  application_controller_output_failed(&controller,controller.model.state.operation_id,DIMMER_FAULT_SECONDARY_UNAVAILABLE);
  assert(!controller.model.state.on&&!controller.output_on);
  assert(platform_io_apply(false,level)==-EIO&&gate==0);
  /* A fresh OFF initialization after inspection recovers without an ON pulse. */
  have_handoff=false;ready=false;failed=false;
  assert(platform_io_init(false,level)==0&&gate==0&&phase==0);
  assert(platform_io_apply(true,level)==0&&gate==1);
 }else{
  assert(error==0&&!failed&&gate==1&&phase==1&&off_writes==before);
 }
 assert(platform_io_apply(false,level)==0&&gate==0);
 assert(unsafe_phase_changes==0);
 /* A generic input-init error gives no new OFF evidence: retain uncertainty. */
 have_handoff=false;ready=false;failed=false;gpio_error=-ENODEV;gate=1;phase=1;
 application_controller_init(&controller,&config,true,88,&callbacks,NULL,0);
 error=platform_io_init(true,88);assert(error==-ENODEV&&gate==1);
 startup_failure(error);
 assert(controller.model.state.on&&controller.output_on&&controller.model.state.fault.active);
 gpio_error=0;
 gate=phase=compare=triggers=off_writes=unsafe_phase_changes=0;
 have_handoff=ready=failed=recovering=input_valid=false;last_raw=-32768;
}
'''.replace('ACTUAL_PLATFORM_FUNCTIONS',init+'\n'+apply).replace('ACTUAL_STARTUP_FAILURE',startup)
   source=(d/'test.c').read_text().replace('int main(void){',glue+'\nint main(void){\n legacy_warm_handoff();')
   source=source.replace('research_output_init_at_level_phase(0,0)==-EBUSY&&phase==1&&gate==1',
                         'research_output_init_at_level_phase(0,0)==-EBUSY&&phase==1&&gate==0')
   (d/'test.c').write_text(source)
   units=[str(ROOT/'firmware/research/src/research_output.c'),str(ROOT/'firmware/research/src/research_protocol.c'),
          *[str(ROOT/'firmware/src'/name) for name in ['dimmer_config.c','settings_record.c','vimar_level.c','application_controller.c','dimmer_model.c','gesture_classifier.c','local_action_mapper.c','led_controller.c']],str(d/'test.c')]
   for mode in (0,1):
    for protected in (False,True):
     exe=str(d/f'output-{mode}-{protected}')
     command=['cc','-std=c11','-Wall','-Wextra','-Werror','-DCONFIG_RESEARCH_STOCK_OUTPUT=1',
       f'-DCONFIG_RESEARCH_STOCK_CONFIG19={mode}',*(['-DCONFIG_VIMAR_P031_PROTECTION=1'] if protected else []),
       '-I',str(d),'-I',str(ROOT/'firmware/src'),'-I',str(ROOT/'firmware/research/src'),*units,'-o',exe]
     subprocess.run(command,check=True)
     subprocess.run([exe],check=True)
