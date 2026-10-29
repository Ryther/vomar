"""Healthy-boot persistence does not erase the only surviving fatal record."""
from pathlib import Path
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[3]

@pytest.fixture(scope='module')
def persistence(tmp_path_factory):
    d=tmp_path_factory.mktemp('fault-persistence')
    headers={
      'zephyr/kernel.h':'#include <stdint.h>\nstatic inline unsigned irq_lock(void){return 0;}\nstatic inline void irq_unlock(unsigned x){(void)x;}\nstatic inline unsigned __get_CONTROL(void){return 0;}\nstatic inline uint32_t __get_PRIMASK(void){return 0;}\nstatic inline void __disable_irq(void){}\nstatic inline void __set_PRIMASK(uint32_t x){(void)x;}\n',
      'zephyr/settings/settings.h':'#include <stddef.h>\n#include <sys/types.h>\nssize_t settings_load_one(const char*,void*,size_t);\nint settings_save_one(const char*,const void*,size_t);\n',
      'hal/nrf_power.h':'#define NRF_POWER ((void*)0)\nstatic inline unsigned nrf_power_gpregret_get(void*p,unsigned n){(void)p;(void)n;return 0;}\n',
      'build.h':'#include <stdint.h>\nstatic const uint8_t vimar_fault_build_id[16]={1,2,3};\n',
      'force.h':'#include <stdint.h>\nextern volatile uint32_t test_window[64];\n',
    }
    for name,text in headers.items():
        p=d/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
    h=d/'test.c';h.write_text(r'''
#include <assert.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include "fault_diag.h"
#include "fault_diag_zephyr.h"
#include "build.h"
volatile uint32_t test_window[64];
static uint32_t durable[64];static int has_durable,save_error,readback_error,save_count;
ssize_t settings_load_one(const char*k,void*p,size_t n){
 assert(strcmp(k,"vimar/fault_diag")==0&&n==256);
 if(readback_error&&save_count)return -EIO;
 if(!has_durable)return 0;memcpy(p,durable,256);return 256;
}
int settings_save_one(const char*k,const void*p,size_t n){
 assert(strcmp(k,"vimar/fault_diag")==0&&n==256);save_count++;
 if(save_error)return -EIO;memcpy(durable,p,256);has_durable=1;return 0;
}
int main(int argc,char**argv){
 assert(argc==3);int scenario=atoi(argv[1]);int tagged=atoi(argv[2]);struct fault_diag_context c;
 uint32_t source=tagged?UINT32_C(0xa1ff007c):2;int32_t line=tagged?652:914,code=tagged?-29:-11;
 uint8_t other[16]={9};fault_diag_init(&c,test_window,scenario==4?other:vimar_fault_build_id,17);
 assert(fault_diag_capture_error(&c,source,line,code));
 assert(fault_diag_capture_abort(&c,0x1235,0x20001000,0x20002000,0,0,0));
 if(scenario==1)save_error=1;
 if(scenario==2)readback_error=1;
 if(scenario==3||scenario==5||scenario==6){memcpy(durable,(const void*)test_window,256);has_durable=1;
 if(scenario==3)fault_diag_acknowledge(&c);
 if(scenario==5)test_window[31]=0;
 if(scenario==6)test_window[63]=0;
 }
 vimar_fault_diag_boot(18);
 uint8_t chunks[8][33];uint32_t status;vimar_fault_diag_export(chunks,&status);
 if(scenario==4){assert((status&39)==39);assert(test_window[31]==0);}
 assert(status&2);
 uint32_t output[64];for(unsigned i=0;i<8;i++){assert(chunks[i][0]==32);memcpy((uint8_t*)output+i*32,chunks[i]+1,32);}
 struct fault_diag_record r;assert(fault_diag_read(output,0,scenario==4?other:vimar_fault_build_id,&r));assert(r.source==source&&r.line==line&&r.error==code&&r.boot_sequence==17);
 if(scenario==1||scenario==2){assert(status&8);assert(test_window[31]==FAULT_DIAG_COMMIT);save_error=readback_error=0;vimar_fault_diag_boot(19);vimar_fault_diag_export(chunks,&status);}
 assert((status&7)==7);assert(test_window[31]==0&&test_window[63]==0);
 assert(fault_diag_read(durable,0,scenario==4?other:vimar_fault_build_id,&r));assert(r.source==source&&r.error==code&&r.line==line);
 assert(fault_diag_read(durable,1,scenario==4?other:vimar_fault_build_id,&r));assert(r.lr==0x1235);
 vimar_fault_diag_boot(20);vimar_fault_diag_export(chunks,&status);assert((status&7)==7);
}
''')
    exe=d/'test';cmd=['cc','-std=c11','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=undefined','-DCONFIG_VIMAR_FAULT_DIAGNOSTICS=1','-DRETAINED=test_window','-DVIMAR_FAULT_BUILD_ID_HEADER="build.h"','-include',str(d/'force.h'),'-I'+str(d),'-I'+str(ROOT/'firmware/src'),str(h),str(ROOT/'firmware/src/fault_diag.c'),str(ROOT/'firmware/src/fault_diag_zephyr.c'),'-o',str(exe)]
    subprocess.run(cmd,check=True,capture_output=True,text=True);return exe

@pytest.mark.parametrize('scenario',range(7))
@pytest.mark.parametrize('tagged',[False,True])
def test_durable_readback_required_before_acknowledging_capture(persistence,scenario,tagged):
    subprocess.run([str(persistence),str(scenario),str(int(tagged))],check=True,timeout=5)
