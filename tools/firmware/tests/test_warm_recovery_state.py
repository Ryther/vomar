"""Host checks for recovery ordering and remembered OFF level; no hardware I/O."""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def function(path, name, signature):
    source = (ROOT / path).read_text()
    match = re.search(signature + r'\n\{.*?\n\}', source, re.S)
    if match is None:
        raise AssertionError(f'{name} must implement warm recovery state preservation')
    return match.group(0)


def run_c(source):
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary)
        (path/'test.c').write_text(source)
        result = subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(path/'test.c'),'-o',str(path/'test')],capture_output=True,text=True)
        if result.returncode:
            raise AssertionError(result.stderr)
        subprocess.run([str(path/'test')],check=True)


class WarmRecoveryStateTests(unittest.TestCase):
    def test_state_flush_precedes_handoff_marker_and_failure_prevents_reboot(self):
        body = function('firmware/src/platform_io_vimar.c','request_connection',r'static int request_connection\(bool bluetooth\)')
        run_c(r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <errno.h>
static bool recovering;
static int last_raw=-32768,io,stage,flush_error,protection_error,intent_error;
static bool pairing_mode;
static bool vimar_power_protection_blocked(void){return false;}
static int vimar_power_protection_flush(void){assert(stage==2);if(protection_error)return protection_error;stage=3;return 0;}
#define BOOT_MODE_TYPE_BOOTLOADER 1
#define SYS_REBOOT_COLD 1
#define LOG_ERR(...) ((void)0)
static void zigbee_device_cancel_gestures(void) {}
int zigbee_device_prepare_recovery(void) { assert(stage==0); if(flush_error)return flush_error; stage=1;return 0; }
static int research_handoff_prepare(void *p,int raw) { (void)p;assert(stage==1&&raw==-32768);stage=2;return 0; }
static int bootmode_set(int mode) { (void)mode;assert(stage==3);stage=4;return 0; }
static int bootmode_clear(void){assert(stage==3);stage=4;return 0;}
static int connection_intent_request(void){assert(stage==4);if(intent_error)return intent_error;stage=5;return 0;}
static int set(void *p,int value) { (void)p;(void)value;return 0; }
static void sys_reboot(int mode) { (void)mode;assert(stage==(pairing_mode?5:4));stage=6; }
''' + body + r'''
int main(void) {
 flush_error=-5;assert(request_connection(true)==-5);assert(stage==0&&!recovering);
 flush_error=0;protection_error=-6;assert(request_connection(true)==-6);assert(stage==2&&!recovering);
 stage=0;protection_error=0;assert(request_connection(true)==0);assert(stage==6&&recovering);
 assert(request_connection(true)==-EBUSY);
 recovering=false;stage=0;pairing_mode=true;intent_error=-7;
 assert(request_connection(false)==-7&&stage==4&&!recovering);
 stage=0;intent_error=0;assert(request_connection(false)==0&&stage==6&&recovering);
 return 0;
}
''')

    def test_warm_off_uses_remembered_level_on_uses_exact_decoded_and_cold_keeps_fallback(self):
        body = function('firmware/src/zigbee_device.c','restore_warm_handoff',r'static void restore_warm_handoff\(uint8_t remembered_level\)')
        run_c(r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
static struct { bool on;uint8_t level; } controller;
static int warm;
static bool decoded_on;
static uint8_t decoded_level;
static int platform_io_restore(bool *on,uint8_t *level) { *on=decoded_on;*level=decoded_level;return warm; }
static void application_controller_restore_handoff(void *c,bool on,uint8_t level) { (void)c;controller.on=on;controller.level=level; }
''' + body + r'''
int main(void) {
 warm=1;decoded_on=false;decoded_level=254;
 controller.on=true;controller.level=180; /* fallback ON must not replace remembered OFF64 */
 restore_warm_handoff(64);assert(!controller.on&&controller.level==64);
 controller.on=false;controller.level=254;restore_warm_handoff(73);assert(!controller.on&&controller.level==73);
 decoded_on=true;decoded_level=188;restore_warm_handoff(64);assert(controller.on&&controller.level==188);
 warm=0;controller.on=true;controller.level=180;restore_warm_handoff(64);assert(controller.on&&controller.level==180);
 controller.on=false;controller.level=64;restore_warm_handoff(64);assert(!controller.on&&controller.level==64);
 warm=-1;controller.on=true;controller.level=180;restore_warm_handoff(64);assert(controller.on&&controller.level==180);
 return 0;
}
''')

    def test_protected_invalid_handoff_forces_off_instead_of_previous_on(self):
        body = function('firmware/src/zigbee_device.c','restore_warm_handoff',r'static void restore_warm_handoff\(uint8_t remembered_level\)')
        run_c(r"""
#define CONFIG_VIMAR_P031_PROTECTION 1
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
static struct {bool on;uint8_t level;} controller;
static int platform_io_restore(bool *on,uint8_t *level){(void)on;(void)level;return -1;}
static void application_controller_restore_handoff(void *c,bool on,uint8_t level){(void)c;controller.on=on;controller.level=level;}
"""+body+r"""
int main(void){controller.on=true;controller.level=180;restore_warm_handoff(64);assert(!controller.on&&controller.level==64);return 0;}
""")

    def test_cancel_ack_waits_for_durable_off_and_retries_storage_failure(self):
        body=function('firmware/src/zigbee_device.c','process_protection',r'static void process_protection\(uint64_t now_ms\)')
        run_c(r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
static struct {struct {int config;struct {uint8_t level;} state;} model;} controller;
static bool pending=true,signal_blocked=true,model_blocked,previous_on=true;
static int save_error=-5,saves,acks;
static bool vimar_power_protection_cancel_pending(void){return pending;}
static bool vimar_power_protection_blocked(void){return pending||signal_blocked;}
static void application_controller_set_protection(void*c,bool b,uint64_t now){(void)c;(void)now;model_blocked=b;}
static int app_settings_flush_current(void*c,bool on,uint8_t level){(void)c;assert(!on&&level==64);saves++;if(save_error)return save_error;previous_on=on;return 0;}
static void vimar_power_protection_cancel_acknowledged(void){assert(!previous_on);pending=false;acks++;}
"""+body+r"""
int main(void){
 controller.model.state.level=64;process_protection(10);assert(model_blocked&&pending&&previous_on&&saves==1&&acks==0);
 signal_blocked=false;process_protection(600);assert(model_blocked&&pending&&previous_on&&saves==1);
 save_error=0;process_protection(1010);assert(!model_blocked&&!pending&&!previous_on&&saves==2&&acks==1);
 process_protection(2000);assert(saves==2);return 0;
}
""")

    def test_prepare_flushes_current_controller_state_and_returns_storage_error(self):
        body = function('firmware/src/zigbee_device.c','zigbee_device_prepare_recovery',r'int zigbee_device_prepare_recovery\(void\)')
        run_c(r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
struct dimmer_config { int token; };
struct dimmer_state { bool on;uint8_t level; };
static struct { struct { struct dimmer_config config; struct dimmer_state state; } model; } controller;
static const struct dimmer_state *application_controller_state(void *c) { (void)c;return &controller.model.state; }
static int app_settings_flush_current(const struct dimmer_config *c,bool on,uint8_t level) {
 assert(c->token==42&&!on&&level==64);return -5;
}
"""+body+r"""
int main(void) {
 controller.model.config.token=42;controller.model.state.on=false;controller.model.state.level=64;
 assert(zigbee_device_prepare_recovery()==-5);return 0;
}
""")
