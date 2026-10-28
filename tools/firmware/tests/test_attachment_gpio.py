"""The real GPIO adapter is compiled against synthetic Zephyr boundaries."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]

class AttachmentGPIOTests(unittest.TestCase):
    def test_interrupt_capture_boot_guard_and_selector_suppression(self):
        with tempfile.TemporaryDirectory() as directory:
            d = Path(directory)
            headers = {
                "zephyr/kernel.h": """
#include <stdint.h>
#include <stdbool.h>
#define CONFIG_SYS_CLOCK_TICKS_PER_SEC 32768
#define BUILD_ASSERT(a) _Static_assert(a, #a)
#define ARG_UNUSED(x) (void)(x)
#define BIT(x) (1U << (x))
struct k_spinlock {int unused;};typedef int k_spinlock_key_t;
static inline int k_spin_lock(struct k_spinlock *l){(void)l;return 0;}
static inline void k_spin_unlock(struct k_spinlock *l,int k){(void)l;(void)k;}
extern uint32_t clock_ticks;static inline uint64_t k_uptime_ticks(void){return clock_ticks;}
""",
                "zephyr/drivers/gpio.h": """
#include <stdint.h>
#include <stdbool.h>
struct device {int unused;};struct gpio_dt_spec {const struct device *port;int pin;int dt_flags;};
struct gpio_callback {void (*fn)(const struct device *,struct gpio_callback *,uint32_t);};
#define DT_ALIAS(a) 0
#define GPIO_DT_SPEC_GET(a,b) {&port,9,4}
#define GPIO_INPUT 1
#define GPIO_PULL_UP 4
#define GPIO_INT_EDGE_BOTH 6
extern struct device port;extern int raw_level,read_error,irq_flags,config_flags,init_error;
static inline bool gpio_is_ready_dt(const struct gpio_dt_spec *s){(void)s;return true;}
static inline int gpio_pin_configure_dt(const struct gpio_dt_spec *s,int f){config_flags=s->dt_flags|f;return init_error;}
static inline void gpio_init_callback(struct gpio_callback *c,void (*f)(const struct device *,struct gpio_callback *,uint32_t),uint32_t pins){(void)pins;c->fn=f;}
extern struct gpio_callback *registered_callback;
static inline int gpio_add_callback(const struct device *p,struct gpio_callback *c){(void)p;registered_callback=c;return 0;}
static inline int gpio_remove_callback(const struct device *p,struct gpio_callback *c){(void)p;(void)c;registered_callback=0;return 0;}
static inline int gpio_pin_interrupt_configure_dt(const struct gpio_dt_spec *s,int f){(void)s;irq_flags=f;return 0;}
static inline int gpio_pin_get_raw(const struct device *p,int pin){(void)p;(void)pin;return read_error?-5:raw_level;}
""",
                "zephyr/logging/log.h": "#define LOG_MODULE_REGISTER(a,b)\n#define LOG_LEVEL_INF 1\n#define LOG_ERR(...)\n",
            }
            for name, value in headers.items():
                path = d / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value)
            source = d / "gpio.c"
            source.write_text(r'''
#include "zephyr/kernel.h"
#include "zephyr/drivers/gpio.h"
#include "vimar_attachment_gpio.h"
#include "application_controller.h"
#include <assert.h>
struct device port;uint32_t clock_ticks;
int raw_level=1,read_error,irq_flags,config_flags,init_error;
struct gpio_callback *registered_callback;
static int edges,cancels;static bool state,settled;
static struct application_controller controller;
static unsigned outputs;
static void output(void *ctx,uint32_t op,bool on,uint8_t level){(void)ctx;outputs++;application_controller_feedback(&controller,op,on,level);}
void zigbee_device_attachment_edge_at(bool pressed,uint64_t now){edges++;state=pressed;application_controller_attachment_edge(&controller,pressed,now);}
void zigbee_device_attachment_settled(bool value){settled=value;application_controller_attachment_settled(&controller,value);}
void zigbee_device_cancel_gestures(void){cancels++;application_controller_cancel_gestures(&controller);vimar_attachment_gpio_cancel();application_controller_attachment_edge(&controller,false,(uint64_t)clock_ticks*1000/32768);state=false;}
static void at(uint64_t ms){clock_ticks=(uint32_t)(ms*32768/1000);}
static void pulse(uint64_t ms){at(ms);raw_level=0;registered_callback->fn(&port,registered_callback,BIT(9));at(ms+5);raw_level=1;registered_callback->fn(&port,registered_callback,BIT(9));}
static void poll(uint64_t ms,bool block){at(ms);vimar_attachment_gpio_tick(ms,block);application_controller_tick(&controller,ms);}
int main(void){
 struct dimmer_config cfg=dimmer_config_defaults();
 struct application_callbacks callbacks={.secondary_request=output};
 application_controller_init(&controller,&cfg,false,100,&callbacks,0,0);
 assert(vimar_attachment_gpio_init()==0);assert(config_flags==(GPIO_INPUT|GPIO_PULL_UP));assert(irq_flags==GPIO_INT_EDGE_BOTH);
 poll(0,false);poll(50,false);assert(edges==0&&settled);
 for(uint64_t ms=60;ms<240;ms+=20){pulse(ms);assert(edges==(state?1:0));poll(ms+5,false);}
 assert(edges==1&&state);
 /* Raw train cessation pauses long/steps before the stable release edge. */
 poll(260,false);assert(!settled&&state);poll(310,false);assert(edges==2&&!state);
 assert(outputs==1&&controller.model.state.on);
 for(uint64_t ms=320;ms<440;ms+=20){pulse(ms);poll(ms+5,false);}assert(state);
 poll(445,true);assert(!state&&cancels>0&&!settled);
 for(uint64_t ms=460;ms<540;ms+=20){pulse(ms);poll(ms+5,true);}assert(!state);
 for(uint64_t ms=560;ms<700;ms+=20){poll(ms,false);}assert(!state);
 for(uint64_t ms=720;ms<850;ms+=20){pulse(ms);poll(ms+5,false);}assert(state);
 /* A stalled consumer cancels its old assertion. The very first subsequent
  * complete short press must work; cancellation cannot consume another click. */
 poll(1100,false);assert(!state&&!controller.attachment_pressed&&outputs==1);
 poll(1150,false);poll(1190,false);
 for(uint64_t ms=1200;ms<1320;ms+=20){pulse(ms);poll(ms+5,false);}
 poll(1340,false);poll(1380,false);
 assert(outputs==2&&!controller.model.state.on);
 /* Keep pulses flowing across selector exit: no newly asserted command is
  * permitted until this same held input first becomes stably quiet. */
 for(uint64_t ms=1400;ms<1560;ms+=20){pulse(ms);poll(ms+5,true);}
 for(uint64_t ms=1560;ms<1700;ms+=20){pulse(ms);poll(ms+5,false);}
 assert(!state&&!controller.attachment_pressed&&outputs==2);
 poll(1720,false);poll(1760,false);
 for(uint64_t ms=1800;ms<1920;ms+=20){pulse(ms);poll(ms+5,false);}
 poll(1940,false);poll(1980,false);
 assert(outputs==3&&controller.model.state.on);
 /* A network command arriving during the 40 ms rising debounce must cancel
  * that already active wired input through release, before a stable edge. */
 pulse(2000);poll(2005,false);assert(!state&&!settled);
 at(2010);zigbee_device_cancel_gestures();
 application_controller_command(&controller,false,100,DIMMER_SOURCE_ZIGBEE,2010);
 assert(outputs==4&&!controller.model.state.on);
 for(uint64_t ms=2020;ms<2120;ms+=20){pulse(ms);poll(ms+5,false);}
 poll(2140,false);poll(2180,false);
 assert(outputs==4&&!controller.model.state.on);
 for(uint64_t ms=2200;ms<2320;ms+=20){pulse(ms);poll(ms+5,false);}
 poll(2340,false);poll(2380,false);assert(outputs==5&&controller.model.state.on);
 /* The IRQ may capture the train before the application has polled even once.
  * Cancelling that unsampled train must also require release before rearming. */
 pulse(2400);at(2410);zigbee_device_cancel_gestures();
 application_controller_command(&controller,false,100,DIMMER_SOURCE_ZIGBEE,2410);
 for(uint64_t ms=2420;ms<2520;ms+=20){pulse(ms);poll(ms+5,false);}
 poll(2540,false);poll(2580,false);assert(outputs==6&&!controller.model.state.on);
 for(uint64_t ms=2600;ms<2720;ms+=20){pulse(ms);poll(ms+5,false);}
 poll(2740,false);poll(2780,false);assert(outputs==7&&controller.model.state.on);
 for(uint64_t ms=2800;ms<2920;ms+=20){pulse(ms);poll(ms+5,false);}assert(state);
 read_error=1;registered_callback->fn(&port,registered_callback,BIT(9));poll(2920,false);assert(!state&&!settled);
 assert(outputs==7);
 return 0;
}
''')
            executable = d / "gpio"
            names = ["vimar_attachment_gpio", "vimar_attachment", "application_controller",
                     "dimmer_config", "dimmer_model", "gesture_classifier",
                     "local_action_mapper", "led_controller"]
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(d), "-I", str(ROOT / "firmware/src"), str(source), *(str(ROOT / "firmware/src" / f"{name}.c") for name in names), "-o", str(executable)], check=True)
            subprocess.run([str(executable)], check=True)
