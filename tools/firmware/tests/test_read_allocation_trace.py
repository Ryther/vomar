"""Synthetic wire records exercise decoding, coherence and exact ELF identity."""
import json
import struct
import subprocess
import sys

import pytest
from tools.firmware import read_allocation_trace as decoder
from tools.firmware.tests.test_ownership_link_audit import crosscompiler


def record(sequence=1, flags=15):
    data=bytearray(48)
    struct.pack_into('<IIII',data,0,sequence,1000,0x12345,1216)
    data[16:21]=bytes.fromhex('aaaaaaaa0a')
    data[21:28]=bytes([flags,8 if flags&4 else 0,9,9,3,40,15])
    struct.pack_into('<IIII',data,28,0x23457,0x34569,0x4567b,50)
    data[44:46]=bytes([1,8])
    return bytes(data)


def capture():
    data={'boot_sequence':31,'boot_sequence_after':31,'firmware_build_id':'ab'*16,
          'allocation_trace_dropped':0,'allocation_trace_lifetime_gaps':0,
          'allocation_trace_metadata':struct.pack('<BBBBIIII',1,48,32,1,1,0,0,1).hex(),
          'allocation_trace_first':record().hex(),'allocation_trace_latest':record().hex()}
    for i in range(32):data[f'allocation_trace_history_{i}']=(record() if i==0 else bytes(48)).hex()
    for i in range(14):data[f'allocation_trace_holders_{i}']=(struct.pack('<I',1)+bytes(36)).hex()
    return data


def test_record_distinguishes_storage_and_quota_without_claiming_physical_cause():
    parsed=decoder.decode_record(record())
    assert parsed['direction']=='IN' and parsed['requested_bytes']==1216
    assert parsed['allocation_path']=='storage_refused' and parsed['caller']==0x12345
    assert parsed['occupied_units']==18 and parsed['queue']['used']==3
    assert decoder.decode_record(record(flags=3))['allocation_path']=='quota_before_storage'


def test_capture_rejects_mixed_samples_and_reports_partial_coverage():
    data=capture();parsed=decoder.decode_capture(data)
    assert parsed['current']['complete'] and parsed['current']['latest']['sequence']==1
    data['allocation_trace_history_0']=record(2).hex()
    with pytest.raises(ValueError,match='history'):decoder.decode_capture(data)
    data=capture();data['allocation_trace_holders_0']=(struct.pack('<I',2)+bytes(36)).hex()
    with pytest.raises(ValueError,match='holder'):decoder.decode_capture(data)
    data=capture();data['boot_sequence_after']=32
    with pytest.raises(ValueError,match='boot'):decoder.decode_capture(data)
    data=capture();del data['allocation_trace_history_0']
    assert not decoder.decode_capture(data)['current']['complete']


def test_duplicate_records_must_agree_before_marking_complete():
    data=capture();data['allocation_trace_first']=record(99).hex()
    with pytest.raises(ValueError,match='first'):decoder.decode_capture(data)
    data=capture();latest=bytearray(record());struct.pack_into('<I',latest,8,0xdeadbeef)
    data['allocation_trace_latest']=latest.hex()
    with pytest.raises(ValueError,match='latest'):decoder.decode_capture(data)


def test_wrapped_counter_distinguishes_initial_first_from_current_sequence_one():
    data=capture()
    data['allocation_trace_metadata']=struct.pack('<BBBBIIII',1,48,32,224,1,0xffffffe1,0,1).hex()
    for age in range(32):
        seq=(1-age)&0xffffffff
        value=bytearray(record(seq));struct.pack_into('<I',value,8,0xdeadbeef)
        data[f'allocation_trace_history_{(seq-1)%32}']=value.hex()
        if age==0:data['allocation_trace_latest']=value.hex()
    assert decoder.decode_capture(data)['current']['complete']


def test_holder_precision_and_unknown_origins_cannot_be_promoted():
    data=capture()
    for name in ('allocation_trace_first','allocation_trace_latest','allocation_trace_history_0'):
        raw=bytearray.fromhex(data[name]);raw[21]|=16;data[name]=raw.hex()
    raw=struct.pack('<I',1)+struct.pack('<IIBBBB',0x4567b,50,1,1,0,3)+bytes(24)
    data['allocation_trace_holders_0']=raw.hex()
    assert not decoder.decode_capture(data)['current']['holders'][0]['age_exact']
    data=capture()
    raw=struct.pack('<I',1)+struct.pack('<IIBBBB',0,50,1,1,255,1)+bytes(24)
    data['allocation_trace_holders_0']=raw.hex()
    assert not decoder.decode_capture(data)['current']['attribution_complete']


def test_invalid_lengths_and_flags_are_rejected():
    for value in (b'',record()+b'\x00',record()[:-1]):
        with pytest.raises(ValueError):decoder.decode_record(value)
    data=bytearray(record());data[21]=8
    with pytest.raises(ValueError):decoder.decode_record(bytes(data))


def test_previous_commit_keeps_its_own_build_boot_and_crc():
    import zlib
    prefix=struct.pack('<IIII',0x414c4c43,1,7,12)+bytes.fromhex('cd'*16)+record()
    raw=prefix+struct.pack('<II',zlib.crc32(prefix),0x41545243)+bytes(8)
    data=capture();data['allocation_trace_retained_status']=7
    for i in range(3):data[f'allocation_trace_previous_{i}']=raw[32*i:32*i+32].hex()
    previous=decoder.decode_capture(data)['previous']
    assert previous['build_id']=='cd'*16 and previous['boot_sequence']==12
    damaged=bytearray(raw);damaged[20]^=1
    data['allocation_trace_previous_0']=damaged[:32].hex()
    with pytest.raises(ValueError,match='CRC'):decoder.decode_capture(data)


def test_cli_decodes_saved_capture_without_network(tmp_path):
    data=tmp_path/'capture.json';data.write_text(json.dumps(capture()))
    p=subprocess.run([sys.executable,'-B','-m','tools.firmware.read_allocation_trace',str(data)],capture_output=True,text=True)
    assert p.returncode==0,p.stderr
    assert json.loads(p.stdout)['current']['metadata']['total']==1


def test_return_address_resolution_requires_matching_embedded_identity(tmp_path,crosscompiler):
    source=tmp_path/'caller.S';source.write_text('''.syntax unified
.thumb
.global caller
.type caller,%function
.thumb_func
caller: bx lr
nop
.size caller,.-caller
.section .rodata
.global vimar_fault_build_id
.type vimar_fault_build_id,%object
vimar_fault_build_id: .fill 16,1,0xab
.size vimar_fault_build_id,16
''')
    elf=tmp_path/'caller.elf'
    subprocess.run([str(crosscompiler),'-mcpu=cortex-m4','-mthumb','-nostdlib','-Wl,-e,caller',str(source),'-o',str(elf)],check=True,capture_output=True)
    from elftools.elf.elffile import ELFFile
    with elf.open('rb') as f:address=ELFFile(f).get_section_by_name('.symtab').get_symbol_by_name('caller')[0]['st_value']
    value=decoder.decode_record(record());value['caller']=(address&~1)+3
    resolved=decoder.resolve_record(value,'ab'*16,elf)
    assert resolved['caller']['symbol']=='caller'
    with pytest.raises(ValueError,match='identity'):decoder.resolve_record(value,'cd'*16,elf)


def test_production_profile_explicitly_reports_capture_unavailable():
    state={'boot_sequence':1,'boot_sequence_after':1,'firmware_build_id':'ab'*16,
           'allocation_trace_metadata':bytes([2])+bytes(19)}
    state['allocation_trace_metadata']=state['allocation_trace_metadata'].hex()
    value=decoder.decode_capture(state)
    assert value['current']['available'] is False
    assert value['current']['history']==[] and value['previous'] is None
    state['allocation_trace_metadata']=(bytes([2,1])+bytes(18)).hex()
    with pytest.raises(ValueError,match='disabled'):decoder.decode_capture(state)
