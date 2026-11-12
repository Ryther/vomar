"""At-event queue evidence keeps corrupt counters raw and never follows callback IDs."""
from pathlib import Path
import struct
import subprocess
import zlib

import pytest
from tools.firmware.read_fault_diagnostics import decode_record

ROOT = Path(__file__).resolve().parents[3]

@pytest.fixture(scope='module')
def queue_capture(tmp_path_factory):
    out = tmp_path_factory.mktemp('queue-capture')
    # ABI-shaped synthetic globals, not vendor code or household data.
    (out / 'zboss_api.h').write_text('#include <stdint.h>\n#include <stddef.h>\n')
    (out / 'zb_mem_config_med.h').write_text('''
#define ZB_CONFIG_SCHEDULER_Q_SIZE 32
struct __attribute__((packed)) entry { union { uint32_t func_ptr, func2_ptr; } u; uint16_t user_param; uint8_t param; };
typedef uint32_t zb_uint_t;
struct queue { uint32_t read_i,write_i,written; struct entry ring_buf[32]; };
typedef struct queue zb_cb_q_buf_t;
extern zb_cb_q_buf_t gc_cb_q;
extern uint32_t gc_sched_q_size;
''')
    harness = out / 'capture.c'
    harness.write_text(r'''
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include "fault_diag.h"
#include "fault_diag_sdk.h"
#include "zb_mem_config_med.h"
zb_cb_q_buf_t gc_cb_q;
uint32_t gc_sched_q_size;
int main(int argc,char **argv) {
 assert(argc==5);
 gc_sched_q_size=strtoul(argv[1],0,0);gc_cb_q.written=strtoul(argv[2],0,0);
 gc_cb_q.read_i=strtoul(argv[3],0,0);gc_cb_q.write_i=strtoul(argv[4],0,0);
 for(unsigned i=0;i<32;i++) gc_cb_q.ring_buf[i].u.func_ptr=0x1001+i*4;
 struct fault_diag_queue queue;
 uint32_t valid=vimar_fault_diag_queue_snapshot(&queue);
 volatile uint32_t window[64]={0};const uint8_t id[16]={1};struct fault_diag_context ctx;
 fault_diag_init(&ctx,window,id,7);
 assert(fault_diag_capture_queue_error(&ctx,0xa1ff007c,652,-29,&queue,valid));
 assert(!fault_diag_capture_assert(&ctx,116,81));
 assert(fault_diag_capture_abort(&ctx,0x1235,0x20000100,0x20000200,0,0,0));
 assert(fwrite((const void*)window,1,256,stdout)==256);
}
''')
    exe = out / 'capture'
    subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',
                    '-fsanitize=undefined','-fno-sanitize-recover=all',
                    '-DCONFIG_VIMAR_FAULT_DIAGNOSTICS=1',
                    '-I'+str(out),'-I'+str(ROOT/'firmware/src'),str(harness),
                    str(ROOT/'firmware/src/zboss_mem_globals.c'),
                    str(ROOT/'firmware/src/fault_diag.c'),'-o',str(exe)],check=True,capture_output=True)
    return exe

@pytest.mark.parametrize('capacity,used,read,write,head,tail',[
    (32,0,0,0,None,None),
    (32,32,0,0,0x1001,0x107d),
    (32,3,30,1,0x1079,0x1001),
    (32,1,31,0,0x107d,0x107d),
    (32,33,0,1,None,None),
    (32,1,32,1,None,None),
    (32,1,0,32,None,None),
    (0xffffffff,0xffffffff,0xffffffff,0xffffffff,None,None),
    (31,2,0,2,None,None),
    (32,2,0,3,None,None),
])
def test_snapshot_exports_bounded_head_tail_and_raw_invalid_state(queue_capture,capacity,used,read,write,head,tail):
    raw=subprocess.run([str(queue_capture),*map(str,(capacity,used,read,write))],check=True,capture_output=True).stdout
    assert len(raw)==256
    assert struct.unpack_from('<H',raw,4)==(2,)
    assert struct.unpack_from('<IIII',raw,56)==(capacity,used,read,write)
    assert struct.unpack_from('<II',raw,120)==(zlib.crc32(raw[:120]),0x434f4d54)
    decoded=decode_record(raw[:128])
    q=decoded['queue']
    assert q['capacity']==capacity and q['used']==used
    assert q['read_index']==read and q['write_index']==write
    assert q['head_callback']==head and q['tail_callback']==tail
    assert decoded['attempted_callback'] is None
    assert 'lr' not in decoded and decoded['original_line']==652
    abort=decode_record(raw[128:])
    assert abort['lr']==0x1235 and 'queue' not in abort


def v2(valid=(1<<18)|(1<<19)|(1<<20)|14,kind=2):
    data=bytearray(128)
    struct.pack_into('<IHHII',data,0,0x46444941,2,128,1,7)
    struct.pack_into('<II',data,32,valid,kind)
    struct.pack_into('<IiiIIIIII',data,44,0xa1ff007c,652,-29,32,32,0,0,0x1001,0x107d)
    struct.pack_into('<II',data,120,zlib.crc32(data[:120]),0x434f4d54)
    return bytes(data)


def test_format2_decoder_keeps_callback_roles_explicit():
    d=decode_record(v2())
    assert d['format']==2 and d['queue']['consistent'] is True
    assert d['queue']['head_callback']==0x1001 and d['queue']['tail_callback']==0x107d
    assert d['attempted_callback'] is None

@pytest.mark.parametrize('valid,kind',[
    ((1<<19)|14,2), ((1<<20)|14,2), ((1<<18)|6,1),
    ((1<<18)|1008,3), ((1<<21)|14,2), ((1<<18)|30,2),
])
def test_queue_flags_cannot_be_reinterpreted_as_registers_or_legacy(valid,kind):
    with pytest.raises(ValueError): decode_record(v2(valid,kind))


def test_symbol_resolution_requires_the_exact_embedded_build_identity(tmp_path):
    from tools.firmware.read_fault_diagnostics import resolve_callbacks
    src=tmp_path/'symbols.c'
    src.write_text('''
#include <stdint.h>
const uint8_t vimar_fault_build_id[16]={1};
__attribute__((noinline)) int queued_callback(int x){return x+3;}
int main(void){return queued_callback(2);}
''')
    elf=tmp_path/'symbols'
    subprocess.run(['cc','-O0','-no-pie',str(src),'-o',str(elf)],check=True)
    listing=subprocess.run(['nm','-S',str(elf)],capture_output=True,text=True,check=True).stdout
    address=int(next(line.split()[0] for line in listing.splitlines() if line.endswith(' queued_callback')),16)
    decoded={'build_id':'01'+'00'*15,'queue':{'head_callback':(address+2)|1,'tail_callback':0xffffffff}}
    result=resolve_callbacks(decoded,elf)
    assert result['callbacks']=={'head_callback':{'symbol':'queued_callback','offset':2},'tail_callback':None}
    decoded['build_id']='02'+'00'*15
    with pytest.raises(ValueError,match='identity'):resolve_callbacks(decoded,elf)
