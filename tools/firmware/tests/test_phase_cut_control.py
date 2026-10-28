"""Exercise phase admission, durable-save ordering, and actual record migration."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]

HARNESS = r'''
#include <assert.h>
#include <errno.h>
#include <string.h>
#include "phase_cut_control.h"
#include "settings_record.h"
#include "zigbee_custom_codec.h"
struct fixture {unsigned calls[3], next;int check_error,save_error,apply_error;};
static int check(void *ctx,enum dimmer_phase_cut_mode mode){struct fixture*f=ctx;assert(mode==DIMMER_PHASE_TRAILING_EDGE);f->calls[f->next++]=1;return f->check_error;}
static int save(void *ctx,enum dimmer_phase_cut_mode mode){struct fixture*f=ctx;assert(mode==DIMMER_PHASE_TRAILING_EDGE);f->calls[f->next++]=2;return f->save_error;}
static int apply(void *ctx,enum dimmer_phase_cut_mode mode){struct fixture*f=ctx;assert(mode==DIMMER_PHASE_TRAILING_EDGE);f->calls[f->next++]=3;return f->apply_error;}
static void admission(void){
 struct fixture f={0};struct phase_cut_io io={&f,check,save,apply};
 struct phase_cut_state state={0};bool saved=true;
 assert(phase_cut_change(DIMMER_PHASE_LEADING_EDGE, DIMMER_PHASE_TRAILING_EDGE,&state,&io,&saved)==0);
 assert(saved&&f.next==3&&f.calls[0]==1&&f.calls[1]==2&&f.calls[2]==3);
 for(unsigned field=0;field<4;field++){
  state=(struct phase_cut_state){.on=field==0,.target_on=field==1,.applied_on=field==2,.transitioning=field==3};
  f=(struct fixture){0};saved=true;
  assert(phase_cut_change(DIMMER_PHASE_LEADING_EDGE,DIMMER_PHASE_TRAILING_EDGE,&state,&io,&saved)==-EBUSY);
  assert(!saved&&f.next==0);
 }
 state=(struct phase_cut_state){0};f=(struct fixture){.check_error=-EIO};
 assert(phase_cut_change(DIMMER_PHASE_LEADING_EDGE,DIMMER_PHASE_TRAILING_EDGE,&state,&io,&saved)==-EIO);assert(!saved&&f.next==1);
 f=(struct fixture){.save_error=-ENOSPC};
 assert(phase_cut_change(DIMMER_PHASE_LEADING_EDGE,DIMMER_PHASE_TRAILING_EDGE,&state,&io,&saved)==-ENOSPC);assert(!saved&&f.next==2);
 f=(struct fixture){.apply_error=-EIO};
 assert(phase_cut_change(DIMMER_PHASE_LEADING_EDGE,DIMMER_PHASE_TRAILING_EDGE,&state,&io,&saved)==-EIO);assert(saved&&f.next==3);
 f=(struct fixture){0};
 assert(phase_cut_change(DIMMER_PHASE_LEADING_EDGE,DIMMER_PHASE_MODE_COUNT,&state,&io,&saved)==-EINVAL);assert(!saved&&f.next==0);
 state.on=true;
 assert(phase_cut_change(DIMMER_PHASE_LEADING_EDGE,DIMMER_PHASE_LEADING_EDGE,&state,&io,&saved)==0);assert(!saved&&f.next==0);
 assert(phase_cut_change(DIMMER_PHASE_LEADING_EDGE,DIMMER_PHASE_TRAILING_EDGE,NULL,&io,&saved)==-EINVAL);
 assert(phase_cut_change(DIMMER_PHASE_LEADING_EDGE,DIMMER_PHASE_TRAILING_EDGE,&state,NULL,&saved)==-EINVAL);
 assert(phase_cut_change(DIMMER_PHASE_LEADING_EDGE,DIMMER_PHASE_TRAILING_EDGE,&state,&io,NULL)==-EINVAL);
}
static void persistence(void){
 struct dimmer_config c=dimmer_config_defaults(),decoded;bool on=false;uint8_t level=0;uint8_t b[128];size_t n;
 assert(c.phase_cut_mode==TEST_DEFAULT_PHASE);
 c.phase_cut_mode=DIMMER_PHASE_MODE_COUNT;assert(!dimmer_config_validate(&c));
 c.phase_cut_mode=DIMMER_PHASE_TRAILING_EDGE;
 assert(settings_record_encode(&c,true,201,b,sizeof(b),&n));assert(b[4]==5);
 assert(settings_record_decode(b,n,&decoded,&on,&level)==SETTINGS_RECORD_OK);
 assert(decoded.phase_cut_mode==DIMMER_PHASE_TRAILING_EDGE&&on&&level==201);
 b[n-5]^=1;assert(settings_record_decode(b,n,&decoded,&on,&level)==SETTINGS_RECORD_BAD_CRC);
 /* Frozen actual v4 encoder output, before this feature changed production. */
 const uint8_t old[]={0x56,0x4d,0x53,0x31,0x04,0x00,0x46,0x00,0x96,0x00,0xfa,0x00,0x64,0x00,0x0a,0x01,0x00,0x00,0x04,0x04,0x58,0x02,0x00,0x00,0x00,0x58,0x02,0x00,0x00,0x00,0x02,0xfe,0x0a,0x00,0x00,0x00,0xfe,0x00,0xff,0x00,0x0a,0x00,0x00,0x4d,0x0a,0x00,0x00,0x64,0x01,0x58,0x39,0x30,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x0a,0xf0,0x58,0x02,0x00,0x00,0x58,0x02,0x00,0x00,0x58,0x02,0x00,0x00,0x00,0x00,0xbc,0xbc,0x30,0xe4};
 assert(settings_record_decode(old,sizeof(old),&decoded,&on,&level)==SETTINGS_RECORD_OK);
 assert(decoded.phase_cut_mode==TEST_DEFAULT_PHASE&&on&&level==88);
 assert(decoded.initial_on_delay_ms==12345&&decoded.led_off.b==77&&decoded.min_level==10&&decoded.max_level==240);
 assert(VIMAR_SCHEMA_VERSION==8&&VIMAR_ATTR_PHASE_CUT_MODE==0x0305&&VIMAR_COMMAND_SET_PHASE_CUT==6);
}
int main(void){admission();persistence();return 0;}
'''

def test_phase_cut_backend_and_historical_settings():
    with tempfile.TemporaryDirectory() as directory:
        folder=Path(directory); source=folder/'test.c';source.write_text(HARNESS)
        for default in [None,0,1]:
            exe=folder/f'test-{default}'
            result=subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',
                *([f'-DCONFIG_RESEARCH_STOCK_CONFIG19={default}'] if default is not None else []),f'-DTEST_DEFAULT_PHASE={default if default is not None else 0}',
                '-I',str(ROOT/'firmware/src'),str(source),
                *[str(ROOT/'firmware/src'/name)for name in ['phase_cut_control.c','dimmer_config.c','settings_record.c','zigbee_custom_codec.c']],
                '-o',str(exe)],capture_output=True,text=True)
            assert result.returncode==0,result.stderr
            subprocess.run([str(exe)],check=True)


def test_zigbee_phase_configuration_admission_and_commit():
    """Compile the real Zigbee adapter helpers against synthetic I/O failures."""
    import re
    source = (ROOT/'firmware/src/zigbee_device.c').read_text()
    start = source.index('static int phase_cut_check(')
    end = source.index('static zb_bool_t custom_command_handler', start)
    helpers = source[start:end]
    harness = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include "application_controller.h"
#include "phase_cut_control.h"
#include "zigbee_custom_codec.h"
#define ARG_UNUSED(x) ((void)(x))
static struct application_controller controller;
static struct { uint8_t phase_cut_mode; } context;
static int check_error,save_error,apply_error;
static unsigned checks,saves,applies,cancels,faults;
static struct dimmer_config durable;
static int platform_io_check_phase_cut(enum dimmer_phase_cut_mode mode){assert(mode<2);++checks;return check_error;}
static int platform_io_set_phase_cut(enum dimmer_phase_cut_mode mode){assert(saves);assert(mode==durable.phase_cut_mode);++applies;return apply_error;}
static int app_settings_flush_current(const struct dimmer_config*c,bool on,uint8_t level){assert(!on&&level==88);++saves;if(!save_error)durable=*c;return save_error;}
static void zigbee_device_cancel_gestures(void){++cancels;}
void application_controller_output_failed(struct application_controller*c,uint32_t op,enum dimmer_fault_code fault){assert(c==&controller&&op==42&&fault==DIMMER_FAULT_SECONDARY_UNAVAILABLE);++faults;}
'''+helpers+r'''
static void reset(void){
 controller=(struct application_controller){0};controller.model.config=dimmer_config_defaults();
 controller.model.config.phase_cut_mode=DIMMER_PHASE_LEADING_EDGE;
 controller.model.state.level=88;controller.model.state.operation_id=42;
 controller.gestures.config=controller.leds.config=controller.model.config;
 context.phase_cut_mode=1;durable=controller.model.config;
 checks=saves=applies=cancels=faults=0;check_error=save_error=apply_error=0;
}
int main(void){
 for(unsigned field=0;field<4;field++){
  reset();controller.model.state.on=field==0;controller.model.state.target_on=field==1;
  controller.output_on=field==2;controller.output_pending=field==3;
  assert(configure_phase_cut(0)==-EBUSY);assert(!checks&&!saves&&!applies&&!cancels);
  assert(context.phase_cut_mode==1&&controller.model.config.phase_cut_mode==1);
 }
 reset();assert(configure_phase_cut(2)==-EINVAL);assert(!checks&&!saves&&!applies);
 reset();controller.model.state.on=true;assert(!configure_phase_cut(1));assert(!checks&&!saves&&!applies);
 reset();check_error=-EIO;assert(configure_phase_cut(0)==-EIO);assert(checks==1&&!saves&&!applies&&!cancels);
 reset();save_error=-ENOSPC;assert(configure_phase_cut(0)==-ENOSPC);assert(saves==1&&!applies&&!cancels);
 assert(context.phase_cut_mode==1&&controller.model.config.phase_cut_mode==1&&durable.phase_cut_mode==1);
 reset();assert(configure_phase_cut(0)==0);assert(checks==1&&saves==1&&applies==1&&cancels==1&&!faults);
 assert(context.phase_cut_mode==0&&controller.model.config.phase_cut_mode==0&&controller.gestures.config.phase_cut_mode==0&&controller.leds.config.phase_cut_mode==0&&durable.phase_cut_mode==0);
 reset();apply_error=-EIO;assert(configure_phase_cut(0)==-EIO);assert(saves==1&&applies==1&&faults==1);
 assert(context.phase_cut_mode==0&&controller.model.config.phase_cut_mode==0&&durable.phase_cut_mode==0);
 return 0;
}
'''
    with tempfile.TemporaryDirectory() as directory:
        folder=Path(directory);src=folder/'test.c';exe=folder/'test';src.write_text(harness)
        result=subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'firmware/src'),str(src),
            *[str(ROOT/'firmware/src'/name) for name in ['phase_cut_control.c','dimmer_config.c','zigbee_custom_codec.c']],
            '-o',str(exe)],capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        subprocess.run([str(exe)],check=True)
    attrs=(ROOT/'firmware/src/zb_vimar_custom.h').read_text()
    assert 'VIMAR_RO(VIMAR_ATTR_PHASE_CUT_MODE' in attrs
    assert 'VIMAR_RW(VIMAR_ATTR_PHASE_CUT_MODE' not in attrs
    assert source.index('platform_io_set_phase_cut(config.phase_cut_mode)') < source.index('error = platform_io_init(')
    assert re.search(r'header.cmd_id==VIMAR_COMMAND_SET_PHASE_CUT.*?zb_buf_len\(buffer\) != 1.*?configure_phase_cut\(payload\[0\]\)',source,re.S)


def test_vimar_phase_adapter_rejects_busy_without_mutating_output():
    import re
    source=(ROOT/'firmware/src/platform_io_vimar.c').read_text()
    functions='\n'.join(re.search(r'int '+name+r'\(enum dimmer_phase_cut_mode phase\)\n\{.*?\n\}',source,re.S).group(0)
        for name in ['platform_io_check_phase_cut','platform_io_set_phase_cut'])
    harness=r'''
#include <assert.h>
#include <errno.h>
#include "dimmer_config.h"
static bool ready,failed,recovering;
static int32_t last_raw=-32768;
static enum dimmer_phase_cut_mode phase_cut=DIMMER_PHASE_LEADING_EDGE;
static unsigned writes,off_calls;
static int gpio_check_error,gpio_apply_error;
static int research_output_check_phase_cut(uint8_t phase){(void)phase;return gpio_check_error;}
static int research_output_set_phase_cut(uint8_t phase){(void)phase;++writes;return gpio_apply_error;}
static int research_output_level(int32_t raw){assert(raw==-32768);++off_calls;return 0;}
'''+functions+r'''
int main(void){
 assert(platform_io_set_phase_cut(DIMMER_PHASE_TRAILING_EDGE)==0);
 assert(phase_cut==0&&!writes&&!off_calls);ready=true;phase_cut=DIMMER_PHASE_LEADING_EDGE;
 last_raw=12000;assert(platform_io_set_phase_cut(0)==-EBUSY);assert(!off_calls&&!writes&&!failed);
 last_raw=-32768;recovering=true;assert(platform_io_set_phase_cut(0)==-EBUSY);assert(!off_calls&&!writes&&!failed);
 recovering=false;gpio_check_error=-EBUSY;assert(platform_io_set_phase_cut(0)==-EBUSY);assert(!off_calls&&!writes&&!failed);
 gpio_check_error=0;assert(platform_io_set_phase_cut(0)==0);assert(writes==1&&phase_cut==0);
 gpio_apply_error=-EIO;assert(platform_io_set_phase_cut(1)==-EIO);assert(failed&&off_calls==1&&last_raw==-32768);
 assert(platform_io_check_phase_cut(1)==-EIO);assert(platform_io_set_phase_cut(2)==-EINVAL);
 return 0;
}
'''
    with tempfile.TemporaryDirectory() as directory:
        folder=Path(directory);src=folder/'test.c';exe=folder/'test';src.write_text(harness)
        result=subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'firmware/src'),str(src),'-o',str(exe)],capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        subprocess.run([str(exe)],check=True)
