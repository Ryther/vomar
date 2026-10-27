"""Actual commissioning callbacks with deterministic SDK signal/ownership IO."""
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[3]


def test_deadline_cancellation_cannot_restart_sdk_joining(tmp_path):
    source=(ROOT/'firmware/src/zigbee_device.c').read_text()
    def function(signature):
        found=re.search(signature+r'\n\{.*?\n\}',source,re.S)
        assert found
        return found.group(0)
    parts=[function(r'static void cancel_pairing\(zb_bufid_t buffer\)'),
           function(r'static void connection_pairing_poll\(uint64_t now\)'),
           function(r'static bool pairing_signal_requires_window\(zb_zdo_app_signal_type_t signal\)'),
           function(r'void zboss_signal_handler\(zb_bufid_t buffer\)')]
    harness=r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#define ARG_UNUSED(x) ((void)(x))
#include "connection_pairing.h"
#include "connection_intent.h"
typedef unsigned char zb_bufid_t;
typedef int zb_zdo_app_signal_hdr_t;
typedef int zb_zdo_app_signal_type_t;
typedef int zb_ret_t;
enum { ZB_BDB_SIGNAL_DEVICE_FIRST_START=1,ZB_BDB_SIGNAL_DEVICE_REBOOT,
 ZB_BDB_SIGNAL_STEERING,ZB_BDB_SIGNAL_TC_REJOIN_DONE,ZB_ZDO_SIGNAL_LEAVE,
 ZB_BDB_SIGNAL_STEERING_CANCELLED,ZB_COMMON_SIGNAL_CAN_SLEEP};
#define RET_OK 0
#define DK_LED2 2
#define IS_ENABLED(x) 0
#define LOG_INF(...) ((void)0)
#define ZB_ERROR_CHECK(x) assert((x)==0)
#define ZB_GET_APP_SIGNAL_STATUS(b) (signal_status)
#define ZB_JOINED() (joined)
static struct connection_pairing connection_pairing;
static bool pairing_expired,pairing_stop_pending,joined,rejoin_started;
static uint64_t now;
static int initial_connection_intent,signal_value,signal_status,default_calls,freed,claims;
static void (*cancel_callback)(zb_bufid_t);
static uint64_t k_uptime_get(void){return now;}
static void zigbee_network_rejoin_abort(void){rejoin_started=false;}
static void bdb_cancel_joining(zb_bufid_t b){assert(b==12);signal_value=ZB_BDB_SIGNAL_STEERING_CANCELLED;}
static int zb_buf_get_out_delayed(void(*callback)(zb_bufid_t)){cancel_callback=callback;return RET_OK;}
static int zb_get_app_signal(zb_bufid_t b,zb_zdo_app_signal_hdr_t **h){(void)b;(void)h;return signal_value;}
static void vimar_fault_diag_signal(uint32_t s,int rc,unsigned role){(void)s;(void)rc;(void)role;}
static void zigbee_led_status_update(zb_bufid_t b,unsigned led){(void)b;(void)led;}
static int zigbee_default_signal_handler(zb_bufid_t b){
 (void)b;default_calls++;
 /* Pinned SDK handles STEERING_CANCELLED with start_network_rejoin(true). */
 if(signal_value==ZB_BDB_SIGNAL_STEERING_CANCELLED)rejoin_started=true;
 return RET_OK;
}
static bool zb_bdb_is_factory_new(void){return !joined;}
static void start_reconciliation(void){}
static void zb_buf_free(zb_bufid_t b){assert(b==8);freed++;}
int connection_intent_claim(void){claims++;return 0;}
'''
    harness+='\n'.join(parts)+r'''
int main(void){
 initial_connection_intent=CONNECTION_ATTEMPTED;
 connection_pairing_start(&connection_pairing,0);rejoin_started=true;
 now=120000;connection_pairing_poll(now);
 assert(pairing_expired&&!rejoin_started&&cancel_callback);
 cancel_callback(12);zboss_signal_handler(8);
 assert(default_calls==0&&!rejoin_started&&freed==1);
 /* Later failure/rejoin/leave signals cannot restart expired joining either. */
 const int terminal[]={ZB_BDB_SIGNAL_STEERING,ZB_BDB_SIGNAL_TC_REJOIN_DONE,ZB_ZDO_SIGNAL_LEAVE};
 for(unsigned i=0;i<3;i++){signal_value=terminal[i];zboss_signal_handler(8);}
 assert(default_calls==0&&!rejoin_started);
 /* A commissioned device upgraded without an intent key cannot open a fresh
  * network search merely because a remote leave removed its credentials. */
 pairing_expired=false;initial_connection_intent=CONNECTION_INITIAL;
 signal_value=ZB_ZDO_SIGNAL_LEAVE;zboss_signal_handler(8);
 assert(default_calls==0&&!rejoin_started);
 initial_connection_intent=CONNECTION_ATTEMPTED;
 /* A reboot after the initial attempt does not reopen an uncommissioned window. */
 signal_value=ZB_BDB_SIGNAL_DEVICE_FIRST_START;zboss_signal_handler(8);
 assert(default_calls==0&&claims==0);
 return 0;
}
'''
    path=tmp_path/'adapter.c';path.write_text(harness)
    executable=tmp_path/'adapter'
    result=subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=undefined',
        '-I',str(ROOT/'firmware/src'),str(path),str(ROOT/'firmware/src/connection_pairing.c'),
        '-o',str(executable)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    subprocess.run([str(executable)],check=True)
