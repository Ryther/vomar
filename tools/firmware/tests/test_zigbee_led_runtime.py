import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


class ZigbeeLedRuntimeTests(unittest.TestCase):
    def test_resolved_readback_expiry_fault_and_bounded_reports(self):
        source = (REPO / 'firmware/src/zigbee_device.c').read_text()
        match = re.search(r'static void refresh_led_runtime\(uint64_t now_ms\)\n\{.*?\n\}', source, re.S)
        self.assertIsNotNone(match, 'controller LED readback must be refreshed and reports bounded')
        harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include "led_controller.h"
#include "connection_pairing.h"
static bool connection_selecting;
static uint64_t connection_selector_since;
static struct connection_pairing connection_pairing;
static bool vimar_power_protection_blocked(void){return false;}
typedef bool zb_bool_t;
struct { uint8_t led_runtime_r,led_runtime_g,led_runtime_b,led_runtime_intensity,led_runtime_effect; bool led_override_active; } context;
struct { struct led_controller leds; struct { struct { bool on; uint8_t level; struct { bool active; } fault; } state; } model; } controller;
static bool led_report_pending;
static uint64_t last_led_report_ms;
#define LED_RUNTIME_REPORT_INTERVAL_MS 250U
static unsigned reports;
static void request_snapshot(void) { ++reports; }
static void platform_io_led(const struct led_output *output, uint64_t now) { (void)output; (void)now; }
'''
        harness += match.group(0) + r'''
int main(void) {
 struct dimmer_config config=dimmer_config_defaults();
 config.led_off=(struct dimmer_led_profile){1,2,3,40};
 config.led_on=(struct dimmer_led_profile){4,5,6,70};
 led_controller_init(&controller.leds,&config);
 refresh_led_runtime(0);
 assert(context.led_runtime_r==1 && context.led_runtime_intensity==40);
 unsigned before=reports;
 for(unsigned i=25;i<=250;i+=25) refresh_led_runtime(i);
 assert(reports<=before+1);
 before=reports;
 for(unsigned i=275;i<=500;i+=25) refresh_led_runtime(i);
 assert(reports==before);
 struct led_output override={9,8,7,65,LED_EFFECT_SLOW_BLINK};
 led_controller_set_override(&controller.leds,&override,500,300);
 refresh_led_runtime(500);
 assert(context.led_runtime_r==9 && context.led_runtime_effect==1 && context.led_override_active);
 controller.model.state.fault.active=true;
 refresh_led_runtime(600);
 assert(context.led_runtime_r==255 && context.led_runtime_intensity==100);
 refresh_led_runtime(800);
 assert(!context.led_override_active);
 controller.model.state.fault.active=false;
 controller.model.state.on=true;
 refresh_led_runtime(825);
 assert(context.led_runtime_r==4 && context.led_runtime_intensity==70);
 before=reports;
 for(unsigned i=850;i<=1100;i+=25) {
   controller.leds.config.led_on.r++;
   refresh_led_runtime(i);
 }
 assert(reports<=before+2);
 connection_selecting=true;connection_selector_since=1200;
 connection_pairing_start(&connection_pairing,1200);
 assert(connection_pairing_joined(&connection_pairing,1300));
 refresh_led_runtime(1300);
 assert(context.led_runtime_r==255&&context.led_runtime_g==255&&context.led_runtime_b==0);
 connection_pairing_tick(&connection_pairing,4300);refresh_led_runtime(4300);
 assert(context.led_runtime_r==255&&context.led_runtime_g==0&&context.led_runtime_b==255);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            test = Path(temporary)/'test.c'
            exe = Path(temporary)/'test'
            test.write_text(harness)
            result = subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(REPO/'firmware/src'),str(test),str(REPO/'firmware/src/led_controller.c'),str(REPO/'firmware/src/connection_pairing.c'),str(REPO/'firmware/src/wireless_status_led.c'),str(REPO/'firmware/src/dimmer_config.c'),'-o',str(exe)], capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            subprocess.run([str(exe)],check=True)

    def test_snapshot_encodes_led_and_estimated_output_attributes(self):
        source = (REPO / 'firmware/src/zigbee_device.c').read_text()
        match = re.search(r'static void send_led_runtime_report\(zb_bufid_t buffer\)\n\{.*?\n\}', source, re.S)
        self.assertIsNotNone(match, 'snapshot must include controller LED state')
        harness = r"""
#include <assert.h>
#include <stdint.h>
#include "zigbee_custom_codec.h"
#include <string.h>
#define ZB_ZCL_ATTR_TYPE_U32 0x23
#define ZB_ZCL_HI_MAX_PAYLOAD_SIZE 66U
#define BUILD_ASSERT(condition, ...) _Static_assert(condition, #condition)
typedef uint8_t zb_bufid_t;
typedef uint8_t zb_uint8_t;
typedef uint16_t zb_uint16_t;
typedef int zb_ret_t;
typedef void zb_addr_u;
#define RET_OK 0
#define ZB_NWK_COORDINATOR_ADDR 0
#define VIMAR_ZIGBEE_ENDPOINT 1
#define ZB_APS_ADDR_MODE_16_ENDP_PRESENT 0
#define ZB_AF_HA_PROFILE_ID 0
#define ZB_ZCL_ATTR_TYPE_U8 0x20
#define ZB_ZCL_ATTR_TYPE_BOOL 0x10
static uint8_t bytes[64];
static unsigned length;
static unsigned completions;
static struct { uint8_t led_runtime_r,led_runtime_g,led_runtime_b,led_runtime_intensity,led_runtime_effect,led_override_active,applied_output_on,applied_output_level,transition_active,last_boot_reason; uint32_t last_reset_flags,boot_sequence; } context={9,8,7,65,1,1,1,123,1,2,0xaabbccdd,0x12345678};
#define ZB_ZCL_START_PACKET(buffer) bytes
#define ZB_ZCL_CONSTRUCT_GENERAL_COMMAND_REQ_FRAME_CONTROL_A(...) ((void)0)
#define ZB_ZCL_CONSTRUCT_COMMAND_HEADER(...) ((void)0)
#define ZB_ZCL_PACKET_PUT_DATA8(command,value) (*(command)++=(value))
#define ZB_ZCL_PACKET_PUT_DATA16_VAL(command,value) do { *(command)++=(value)&255; *(command)++=(value)>>8; } while(0)
#define ZB_ZCL_PACKET_PUT_DATA32_VAL(command,value) do { uint32_t v=(value); for(unsigned j=0;j<4;j++){*(command)++=v;v>>=8;} } while(0)
static void led_runtime_report_sent(zb_bufid_t buffer) { (void)buffer; }
static void zb_buf_free(zb_bufid_t buffer) { (void)buffer; }
static void snapshot_complete(bool success) { assert(!success); ++completions; }
static int zb_zcl_finish_and_send_packet(zb_bufid_t b,uint8_t *end,const zb_addr_u *a,int mode,int ep,int src,int profile,int cluster,void (*cb)(zb_bufid_t)) {
 (void)b;(void)a;(void)mode;(void)ep;(void)src;(void)profile;(void)cb;
 assert(cluster==0xfc00); length=(unsigned)(end-bytes); return RET_OK;
}
"""
        harness += match.group(0) + r"""
int main(void) {
 send_led_runtime_report(1);
 assert(length==54 && completions==0);
 const uint8_t values[]={9,8,7,65,1,1};
 for(unsigned i=0;i<6;i++) {
  assert(bytes[i*4]==i && bytes[i*4+1]==5);
  assert(bytes[i*4+2]==(i==5?0x10:0x20));
  assert(bytes[i*4+3]==values[i]);
 }
 const uint8_t output[]={1,123,1};
 for(unsigned i=0;i<3;i++) {
  assert(bytes[24+i*4]==7+i && bytes[25+i*4]==6);
  assert(bytes[26+i*4]==(i==1?0x20:0x10));
  assert(bytes[27+i*4]==output[i]);
 }
 const uint8_t boot[]={0x0a,0x07,0x20,2,0x0b,0x07,0x23,0xdd,0xcc,0xbb,0xaa,0x0c,0x07,0x23,0x78,0x56,0x34,0x12};
 assert(!memcmp(bytes+36,boot,sizeof(boot)));
 return 0;
}
"""
        with tempfile.TemporaryDirectory() as temporary:
            test=Path(temporary)/'test.c'; exe=Path(temporary)/'test'
            test.write_text(harness)
            result=subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(REPO/'firmware/src'),str(test),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            subprocess.run([str(exe)],check=True)
