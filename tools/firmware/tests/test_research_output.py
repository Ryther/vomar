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
   exe=str(d/'output-test')
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-DCONFIG_RESEARCH_STOCK_OUTPUT=1','-DCONFIG_RESEARCH_STOCK_CONFIG19=1','-I',str(d),'-I',str(ROOT/'firmware/research/src'),str(ROOT/'firmware/research/src/research_output.c'),str(ROOT/'firmware/research/src/research_protocol.c'),str(d/'test.c'),'-o',exe],check=True)
   subprocess.run([exe],check=True)

   guarded=str(d/'output-protected-test')
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-DCONFIG_VIMAR_P031_PROTECTION=1','-DCONFIG_RESEARCH_STOCK_OUTPUT=1','-DCONFIG_RESEARCH_STOCK_CONFIG19=1','-I',str(d),'-I',str(ROOT/'firmware/src'),'-I',str(ROOT/'firmware/research/src'),str(ROOT/'firmware/research/src/research_output.c'),str(ROOT/'firmware/research/src/research_protocol.c'),str(d/'test.c'),'-o',guarded],check=True)
   subprocess.run([guarded],check=True)
