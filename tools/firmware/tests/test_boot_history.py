"""Whole-ring immutable snapshots preserve the existing 88-byte storage record."""
from local_inputs import local_input, sdk_root
from pathlib import Path
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[3]


@pytest.fixture(scope='module')
def history(tmp_path_factory):
 base=tmp_path_factory.mktemp('boot_history')
 headers={
 'zephyr/kernel.h':'''#ifndef TEST_KERNEL_H
#define TEST_KERNEL_H
#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>
struct k_mutex {unsigned depth;};
#define K_MUTEX_DEFINE(n) struct k_mutex n
#define K_FOREVER -1
void test_lock(void);
static inline int k_mutex_lock(struct k_mutex*m,int t){(void)t;assert(!m->depth);m->depth++;test_lock();return 0;}
static inline void k_mutex_unlock(struct k_mutex*m){assert(m->depth==1);m->depth--;}
#endif
''',
 'zephyr/settings/settings.h':'#include <stddef.h>\n#include <sys/types.h>\nssize_t settings_load_one(const char*,void*,size_t);int settings_save_one(const char*,const void*,size_t);\n',
 'hal/nrf_power.h':'#include <stdint.h>\n#define NRF_POWER ((void*)0)\nuint32_t test_resetreas_get(void);void test_resetreas_clear(uint32_t);\nstatic inline uint32_t nrf_power_resetreas_get(void*p){(void)p;return test_resetreas_get();}\nstatic inline void nrf_power_resetreas_clear(void*p,uint32_t n){(void)p;test_resetreas_clear(n);}\n'
 }
 for name,text in headers.items():
  p=base/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
 exe=base/'history'
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=undefined','-fno-sanitize-recover=all',
  '-DCONFIG_VIMAR_P031_PROTECTION=1','-I'+str(base),'-I'+str(ROOT/'firmware/src'),
  str(ROOT/'firmware/src/boot_trace.c'),str(ROOT/'firmware/src/boot_trace_zephyr.c'),
  str(Path(__file__).with_name('boot_history_test.c')),'-o',str(exe)],check=True,capture_output=True)
 return exe


@pytest.mark.parametrize('scenario',['ring','crc','load','save'])
def test_full_mutex_snapshot_history_and_storage_failures(history,scenario):
 subprocess.run([str(history),scenario],check=True)


def test_portable_order_is_ring_order_even_when_sequence_saturates(tmp_path):
 source=tmp_path/'order.c';source.write_text(r'''
#include "boot_trace.h"
#include <assert.h>
#include <string.h>
int main(void){
 struct boot_trace trace={0};struct boot_trace_view view;
 for(unsigned i=0;i<10;i++)boot_trace_begin(&trace,BOOT_IMAGE_MAIN,i);
 assert(!boot_trace_chronological(&trace,&view)&&view.count==6);
 for(unsigned i=0;i<6;i++)assert(view.entries[i].sequence==i+5&&view.entries[i].reset_flags==i+4);
 trace.sequence=UINT32_MAX;
 for(unsigned i=0;i<8;i++)boot_trace_begin(&trace,BOOT_IMAGE_RECOVERY,i+100);
 assert(!boot_trace_chronological(&trace,&view));
 for(unsigned i=0;i<6;i++)assert(view.entries[i].sequence==UINT32_MAX&&view.entries[i].reset_flags==i+102);
 trace.count=7;memset(&view,0xa5,sizeof(view));assert(boot_trace_chronological(&trace,&view)<0);
 for(unsigned i=0;i<sizeof(view);i++)assert(((unsigned char*)&view)[i]==0);
 return 0;
}
''')
 exe=tmp_path/'order'
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I'+str(ROOT/'firmware/src'),str(source),str(ROOT/'firmware/src/boot_trace.c'),'-o',str(exe)],check=True,capture_output=True)
 subprocess.run([str(exe)],check=True)


@pytest.mark.parametrize('canonical',[False,True])
def test_actual_sdk_cbor_history_is_bounded_and_preserves_raw_evidence(tmp_path,canonical):
 import cbor2
 zcbor=local_input(sdk_root()/'modules/lib/zcbor')
 source=tmp_path/'cbor.c';source.write_text(r'''
#include "recovery_boot_history.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
int main(int argc,char**argv){
 struct boot_trace trace={0};struct boot_trace_history history={0};
 for(unsigned i=0;i<8;i++)boot_trace_begin(&trace,BOOT_IMAGE_MAIN,i);
 boot_trace_request(&trace,BOOT_REASON_CHORD);boot_trace_begin(&trace,BOOT_IMAGE_RECOVERY,0);
 boot_trace_request(&trace,BOOT_REASON_ZIGBEE);
 assert(!boot_trace_chronological(&trace,&history.view));
 history.initialized=true;history.loaded_valid=true;history.storage_valid=true;history.load_result=88;
 if(argc>1){history.save_result=atoi(argv[1]);history.storage_valid=false;}
 if(argc>2){
  history.view.sequence=UINT32_MAX;history.view.pending_reason=BOOT_REASON_BOOT_SELECTOR;
  history.load_result=history.decode_result=history.save_result=history.view_result=INT32_MIN;
  for(unsigned i=0;i<6;i++){history.view.entries[i].sequence=UINT32_MAX;history.view.entries[i].reset_flags=UINT32_MAX;history.view.entries[i].reason=BOOT_REASON_BOOT_SELECTOR;}
 }
 unsigned char output[1024];ZCBOR_STATE_E(state,4,output,sizeof(output),1);
 assert(zcbor_map_start_encode(state,8));assert(recovery_boot_history_encode(state,&history));assert(zcbor_map_end_encode(state,8));
 fwrite(output,1,(size_t)(state->payload-output),stdout);
 unsigned char tiny[16];ZCBOR_STATE_E(small,4,tiny,sizeof(tiny),1);
 assert(!recovery_boot_history_encode(small,&history));
 history.view.count=7;ZCBOR_STATE_E(invalid,4,output,sizeof(output),1);assert(!recovery_boot_history_encode(invalid,&history));
 return 0;
}
''')
 exe=tmp_path/'cbor'
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',*(['-DZCBOR_CANONICAL'] if canonical else []),
  '-I'+str(zcbor/'include'),'-I'+str(ROOT/'firmware/src'),'-I'+str(ROOT/'firmware/recovery/src'),
  str(source),str(ROOT/'firmware/src/boot_trace.c'),str(ROOT/'firmware/recovery/src/recovery_boot_history.c'),
  str(zcbor/'src/zcbor_common.c'),str(zcbor/'src/zcbor_encode.c'),'-o',str(exe)],check=True,capture_output=True)
 for save_result in [0,-28]:
  data=subprocess.check_output([str(exe),*([str(save_result)] if save_result else [])]);out=cbor2.loads(data)
  assert len(data)<1024 and out['protocol']==1 and out['record_size']==88 and out['capacity']==6
  assert out['sequence']==9 and out['pending_reason']==2 and out['current_image']==1
  assert out['state']==dict(initialized=True,loaded_valid=True,storage_valid=save_result==0,
                           load_rc=88,decode_rc=0,save_rc=save_result,view_rc=0)
  assert [x['seq'] for x in out['entries']]==[4,5,6,7,8,9]
  assert out['entries'][-1]==dict(seq=9,image=1,reason=3,raw_reset_flags=0)
 maximum=subprocess.check_output([str(exe),'-2147483648','max'])
 max_out=cbor2.loads(maximum)
 assert max_out['sequence']==0xffffffff and len(max_out['entries'])==6
 assert all(e['seq']==0xffffffff and e['raw_reset_flags']==0xffffffff for e in max_out['entries'])
 assert all(max_out['state'][name]==-2147483648 for name in ['load_rc','decode_rc','save_rc','view_rc'])
 assert len(maximum)+8<1024
 # The actual unsigned integration build has2475-byte SMP transport buffers.
 assert len(maximum)+8<=2475
 (tmp_path/'maximum-response-size.txt').write_text(str(len(maximum)+8))


def test_sdk_history_handler_has_only_read_and_snapshots_once(tmp_path):
 import cbor2
 zcbor=local_input(sdk_root()/'modules/lib/zcbor')
 headers={
 'zephyr/mgmt/mcumgr/mgmt/mgmt.h':'''#include <stddef.h>
#include <stdint.h>
struct smp_streamer;
struct mgmt_handler {int(*mh_read)(struct smp_streamer*);int(*mh_write)(struct smp_streamer*);};
struct mgmt_group {const struct mgmt_handler*mg_handlers;size_t mg_handlers_count;uint16_t mg_group_id;};
void mgmt_register_group(struct mgmt_group*);
#define MGMT_ERR_EOK 0
#define MGMT_ERR_EMSGSIZE 7
''',
 'zephyr/mgmt/mcumgr/smp/smp.h':'#include <zcbor_encode.h>\nstruct writer {zcbor_state_t*zs;};struct smp_streamer {struct writer*writer;};\n'
 }
 for name,text in headers.items():
  p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
 source=tmp_path/'handler.c';source.write_text(r'''
#include "recovery_boot_history.h"
#include <zephyr/mgmt/mcumgr/mgmt/mgmt.h>
#include <zephyr/mgmt/mcumgr/smp/smp.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
static struct mgmt_group*registered;static unsigned snapshots;
void mgmt_register_group(struct mgmt_group*g){assert(!registered);registered=g;}
void vimar_boot_trace_history_snapshot(struct boot_trace_history*h){snapshots++;memset(h,0,sizeof(*h));h->initialized=true;h->load_result=-5;}
int main(void){
 recovery_boot_history_register();assert(registered&&registered->mg_group_id==0x8041&&registered->mg_handlers_count==1);
 assert(registered->mg_handlers[0].mh_read&&!registered->mg_handlers[0].mh_write);
 unsigned char output[1024];ZCBOR_STATE_E(state,4,output,sizeof(output),1);
 struct writer writer={.zs=state};struct smp_streamer stream={.writer=&writer};
 assert(zcbor_map_start_encode(state,8));assert(registered->mg_handlers[0].mh_read(&stream)==MGMT_ERR_EOK);
 assert(zcbor_map_end_encode(state,8)&&snapshots==1);fwrite(output,1,(size_t)(state->payload-output),stdout);
 return 0;
}
''')
 exe=tmp_path/'handler'
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-DCONFIG_VIMAR_P031_PROTECTION=1',
  '-I'+str(tmp_path),'-I'+str(zcbor/'include'),'-I'+str(ROOT/'firmware/src'),'-I'+str(ROOT/'firmware/recovery/src'),
  str(source),str(ROOT/'firmware/recovery/src/recovery_boot_history.c'),str(ROOT/'firmware/recovery/src/recovery_boot_history_zephyr.c'),
  str(zcbor/'src/zcbor_common.c'),str(zcbor/'src/zcbor_encode.c'),'-o',str(exe)],check=True,capture_output=True)
 decoded=cbor2.loads(subprocess.check_output([str(exe)]))
 assert decoded['state']['load_rc']==-5 and not decoded['state']['storage_valid'] and decoded['entries']==[]
