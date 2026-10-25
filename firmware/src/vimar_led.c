#include "vimar_led.h"
#include <hal/nrf_gpio.h>
#include <hal/nrf_pwm.h>
#include <zephyr/kernel.h>
#include <errno.h>
/* Exact stock numeric conversion, Zigbee0x3a030. Physical RGB order to verify. */
static uint16_t values[4] __aligned(4);
static uint16_t previous[3]={UINT16_MAX,UINT16_MAX,UINT16_MAX};
static bool ready;
static const nrf_pwm_sequence_t seq={.values.p_raw=values,.length=4};
int vimar_led_render(const struct led_output *o,uint64_t now)
{
 if(!ready)return-ENODEV;
 uint32_t intensity=o->intensity>100?100:o->intensity;
 if(o->effect==LED_EFFECT_SLOW_BLINK&&now%1000>=500)intensity=0;
 const uint8_t rgb[]={o->r,o->g,o->b};uint16_t next[3];bool changed=false;
 for(unsigned i=0;i<3;i++){uint32_t component=rgb[i]*intensity/100;next[i]=(255-component)*6666/255;changed|=next[i]!=previous[i];}
 if(!changed)return 0;
 for(unsigned i=0;i<3;i++)values[i]=next[i];
 nrf_pwm_sequence_set(NRF_PWM0,0,&seq);nrf_pwm_sequence_set(NRF_PWM0,1,&seq);
 nrf_pwm_loop_set(NRF_PWM0,1);nrf_pwm_event_clear(NRF_PWM0,NRF_PWM_EVENT_SEQEND1);
 __DMB();nrf_pwm_task_trigger(NRF_PWM0,NRF_PWM_TASK_SEQSTART1);
 for(unsigned i=0;i<10000;i++){
  if(nrf_pwm_event_check(NRF_PWM0,NRF_PWM_EVENT_SEQEND1)){
   for(unsigned j=0;j<3;j++){previous[j]=next[j];}
   return 0;
  }k_busy_wait(1);
 }
 nrf_pwm_disable(NRF_PWM0);ready=false;return-ETIMEDOUT;
}
int vimar_led_init(void)
{
 const uint32_t pins[]={12,6,8,NRF_PWM_PIN_NOT_CONNECTED};
 nrf_pwm_disable(NRF_PWM0);
 for(unsigned i=0;i<3;i++){nrf_gpio_pin_clear(pins[i]);nrf_gpio_cfg_output(pins[i]);}
 nrf_pwm_pins_set(NRF_PWM0,pins);nrf_pwm_configure(NRF_PWM0,NRF_PWM_CLK_1MHz,NRF_PWM_MODE_UP,6666);
 nrf_pwm_decoder_set(NRF_PWM0,NRF_PWM_LOAD_INDIVIDUAL,NRF_PWM_STEP_AUTO);
 nrf_pwm_shorts_set(NRF_PWM0,0);nrf_pwm_int_set(NRF_PWM0,0);nrf_pwm_enable(NRF_PWM0);ready=true;
 return vimar_led_render(&(struct led_output){0},0);
}
