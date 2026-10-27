"""Exercise the actual report producers and completion callbacks without radio IO."""
from pathlib import Path
import re
import resource
import subprocess

ROOT = Path(__file__).resolve().parents[3]


def test_protection_snapshot_preserves_fields_within_sdk_extended_address_bound(tmp_path):
    source = (ROOT / 'firmware/src/zigbee_device.c').read_text()
    names = ('protection_report_sent', 'send_protection_report',
             'led_runtime_report_sent', 'send_led_runtime_report')
    bodies = []
    for name in names:
        match = re.search(r'static void ' + name + r'\(zb_bufid_t buffer\)\n\{.*?\n\}', source, re.S)
        if match:
            bodies.append((name, match.group(0)))
    assert {'protection_report_sent', 'send_protection_report'} <= {n for n, _ in bodies}
    harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "zigbee_custom_codec.h"
typedef uint8_t zb_bufid_t;
typedef uint8_t zb_uint8_t;
typedef uint16_t zb_uint16_t;
typedef int zb_ret_t;
typedef void zb_addr_u;
typedef void (*callback_t)(zb_bufid_t);
typedef struct { int status; } zb_zcl_command_send_status_t;
#define RET_OK 0
#define ZB_NWK_COORDINATOR_ADDR 0
#define VIMAR_ZIGBEE_ENDPOINT 1
#define ZB_APS_ADDR_MODE_16_ENDP_PRESENT 2
#define ZB_AF_HA_PROFILE_ID 0x0104
#define ZB_ZCL_CMD_REPORT_ATTRIB 0x0a
#define ZB_ZCL_ATTR_TYPE_BOOL 0x10
#define ZB_ZCL_ATTR_TYPE_U8 0x20
#define ZB_ZCL_ATTR_TYPE_U32 0x23
/* Pinned SDK bound with extended source/destination addresses. */
#define ZB_ZCL_HI_MAX_PAYLOAD_SIZE 66U
#define BUILD_ASSERT(condition, ...) _Static_assert(condition, #condition)
static struct {
 uint8_t p031_enabled,p031_raw_level,p031_sample_valid,p031_low_qualified;
 uint8_t p031_signal_inhibit,p031_output_blocked,p031_notification;
 uint32_t p031_trip_count,p031_max_sample_gap_ms,p031_monitor_uptime_s;
 uint8_t last_boot_reason; uint32_t last_reset_flags,boot_sequence;
 uint8_t led_runtime_r,led_runtime_g,led_runtime_b,led_runtime_intensity,led_runtime_effect,led_override_active;
 uint8_t applied_output_on,applied_output_level,transition_active;
} context={1,0,1,1,0,0,1,0x12345678,0x11223344,0x89abcdef,3,0x31415926,0x27182818,10,20,30,40,1,1,0,123,1};
static uint8_t bytes[256], packets[4][66];
static size_t packet_lengths[4];
static unsigned count, frees, completions; static bool completion_success, owned;
static int allocation_error, immediate_error;
static callback_t completion, allocation;
static zb_zcl_command_send_status_t send_status;
#define ZB_ZCL_START_PACKET(buffer) bytes
#define ZB_ZCL_CONSTRUCT_GENERAL_COMMAND_REQ_FRAME_CONTROL_A(ptr,...) (*(ptr)++=0x18)
#define ZB_ZCL_CONSTRUCT_COMMAND_HEADER(ptr,seq,cmd) do { *(ptr)++=(seq); *(ptr)++=(cmd); } while(0)
#define ZB_ZCL_GET_SEQ_NUM() 0x37
#define ZB_ZCL_PACKET_PUT_DATA8(ptr,value) (*(ptr)++=(value))
#define ZB_ZCL_PACKET_PUT_DATA16_VAL(ptr,value) do { uint16_t v=(value); *(ptr)++=v; *(ptr)++=v>>8; } while(0)
#define ZB_ZCL_PACKET_PUT_DATA32_VAL(ptr,value) do { uint32_t v=(value); for(unsigned i=0;i<4;i++){*(ptr)++=v;v>>=8;} } while(0)
#define ZB_BUF_GET_PARAM(buffer,type) (&send_status)
static void zb_buf_free(zb_bufid_t buffer) { assert(buffer==1&&owned); owned=false; ++frees; }
static void snapshot_complete(bool ok) { assert(!owned); ++completions; completion_success=ok; }
static void vimar_fault_diag_report(uint32_t kind,uint32_t length,int rc) {
 (void)kind;(void)rc; assert(count>0&&length==packet_lengths[count-1]);
}
static zb_ret_t zb_buf_get_out_delayed(callback_t cb) {
 assert(!owned&&!allocation);
 if(allocation_error)return allocation_error;
 allocation=cb; return RET_OK;
}
static zb_ret_t zb_zcl_finish_and_send_packet(zb_bufid_t buffer,uint8_t *end,
 const zb_addr_u *addr,int mode,int dst,int ep,int profile,int cluster,callback_t cb) {
 (void)addr;assert(buffer==1&&owned&&mode==2&&dst==1&&ep==1&&profile==0x104&&cluster==0xfc00);
 size_t n=(size_t)(end-bytes);
 assert(n<=ZB_ZCL_HI_MAX_PAYLOAD_SIZE); /* Regression: production1.0.0 emits70. */
 assert(count<4);memcpy(packets[count],bytes,n);packet_lengths[count++]=n;
 if(immediate_error)return immediate_error;
 assert(!completion);completion=cb;return RET_OK;
}
'''
    harness += '\n'.join('static void ' + n + '(zb_bufid_t buffer);' for n, _ in bodies)
    harness += '\n' + '\n'.join(body for _, body in bodies)
    harness += r'''
static void begin(void) {
 count=frees=completions=0;completion_success=false;owned=true;
 completion=allocation=NULL;allocation_error=immediate_error=0;
 send_led_runtime_report(1);
}
static void finish_one(int rc) {
 assert(completion);callback_t cb=completion;completion=NULL;send_status.status=rc;cb(1);
 if(allocation){callback_t next=allocation;allocation=NULL;assert(!owned);owned=true;next(1);}
}
static uint32_t expected(unsigned i) {
 const uint32_t values[]={1,0,1,1,0,0,1,0x12345678,0x11223344,0x89abcdef,3,0x31415926,0x27182818,10,20,30,40,1,1,0,123,1};
 return values[i];
}
static void check_fields(void) {
 unsigned seen[22]={0};
 for(unsigned p=0;p<count;p++) {
  const uint8_t *b=packets[p];size_t n=packet_lengths[p];
  assert(n<=66&&n>=3&&b[0]==0x18&&b[2]==0x0a);
  for(size_t at=3;at<n;) {
   assert(n-at>=4);unsigned id=b[at]|(unsigned)b[at+1]<<8;uint8_t type=b[at+2];at+=3;
   unsigned i;
   if(id>=0x700&&id<=0x70c)i=id-0x700;
   else if(id>=0x500&&id<=0x505)i=13+id-0x500;
   else {assert(id>=0x607&&id<=0x609);i=19+id-0x607;}
   assert(seen[i]++==0);
   unsigned size=(i==7||i==8||i==9||i==11||i==12)?4:1;
   assert(type==(size==4?0x23:(i==1||i==10||(i>=13&&i<=17)||i==20)?0x20:0x10));assert(at+size<=n);
   uint32_t value=0;for(unsigned j=0;j<size;j++)value|=(uint32_t)b[at++]<<(8*j);
   assert(value==expected(i));
  }
 }
 for(unsigned i=0;i<22;i++)assert(seen[i]==1);
}
int main(void) {
 (void)zb_buf_get_out_delayed;
 begin();assert(completions==0);
 finish_one(0);assert(completions==0); /* Snapshot is incomplete until the protection report ACK. */
 finish_one(0);assert(count==2&&frees==2&&completions==1&&completion_success&&!owned);
 check_fields();assert(packet_lengths[0]==57&&packet_lengths[1]==52);
 begin();finish_one(-1);assert(count==1&&frees==1&&completions==1&&!completion_success&&!owned&&!allocation);
 begin();allocation_error=-1;finish_one(0);assert(count==1&&frees==1&&completions==1&&!completion_success&&!owned);
 begin();finish_one(0);finish_one(-1);assert(frees==2&&completions==1&&!completion_success&&!owned);
 immediate_error=-1;owned=true;count=frees=completions=0;completion=allocation=NULL;
 send_led_runtime_report(1);assert(frees==1&&completions==1&&!completion_success&&!owned);
 begin();immediate_error=-1;finish_one(0);assert(frees==2&&completions==1&&!completion_success&&!owned);
 return 0;
}
'''
    path = tmp_path / 'report_test.c'
    path.write_text(harness)
    exe = tmp_path / 'report_test'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-I', str(ROOT / 'firmware/src'), str(path), '-o', str(exe)], check=True)
    def no_core():
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    subprocess.run([str(exe)], check=True, preexec_fn=no_core)
