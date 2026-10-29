import struct,zlib
import pytest
from tools.firmware.read_fault_diagnostics import decode_record,decode_chunks

def record():
    data=bytearray(128);struct.pack_into('<IHHII',data,0,0x46444941,1,128,1,7)
    data[16:32]=bytes(range(16));struct.pack_into('<II',data,32,14,2)
    struct.pack_into('<Iii',data,44,2,914,-17)
    struct.pack_into('<II',data,120,zlib.crc32(data[:120]),0x434f4d54)
    return bytes(data)

def test_signed_error_and_build_identity_are_preserved():
    decoded=decode_record(record(),bytes(range(16)))
    assert decoded['kind']=='checked_error'
    assert decoded['error']==-17 and decoded['source']==2 and decoded['line']==914
    assert 'severity' not in decoded and 'original_location_present' not in decoded
    assert decoded['matches_expected_build'] is True
    assert decode_record(record(),b'x'*16)['matches_expected_build'] is False

def tagged_record(source,line):
    data=bytearray(128)
    struct.pack_into('<IHHII',data,0,0x46444941,1,128,1,7)
    data[16:32]=bytes(range(16))
    struct.pack_into('<II',data,32,0x3fc0f,2)
    struct.pack_into('<IIii',data,40,123,source,line,-17)
    struct.pack_into('<IiIIIIiI',data,80,9,-10,11,12,13,14,-15,16)
    struct.pack_into('<II',data,120,zlib.crc32(data[:120]),0x434f4d54)
    return bytes(data)

@pytest.mark.parametrize('source,severity',[
    (0xa0000000,0),(0xa0020000,2),(0xa0030000,3),
    (0xa07f0000,127),(0xa0ff0000,255),
])
def test_sdk_error_without_original_location_preserves_raw_capture(source,severity):
    decoded=decode_record(tagged_record(source,-2147483648),bytes(range(16)))
    assert decoded=={
        'format':1,'sequence':1,'boot_sequence':7,
        'build_id':'000102030405060708090a0b0c0d0e0f',
        'kind':'sdk_error','valid':0x3fc0f,'matches_expected_build':True,
        'uptime_ms':123,'source':source,'line':-2147483648,'error':-17,
        'signal':9,'signal_status':-10,'stage':11,'role':12,
        'report_kind':13,'report_length':14,'report_status':-15,'phase':16,
        'severity':severity,'original_location_present':False,
    }

@pytest.mark.parametrize('source,line,file_id',[
    (0xa1ff0000,0,0),(0xa1ff1234,-25,0x1234),
    (0xa1ffffff,2147483647,0xffff),(0xa1ff5678,-2147483648,0x5678),
])
def test_sdk_error_with_original_location_retains_signed_line(source,line,file_id):
    decoded=decode_record(tagged_record(source,line))
    assert decoded['kind']=='sdk_error' and decoded['severity']==255
    assert decoded['original_location_present'] is True
    assert decoded['original_file_id']==file_id and decoded['original_line']==line
    assert decoded['source']==source and decoded['line']==line and decoded['error']==-17
    assert decoded['build_id']=='000102030405060708090a0b0c0d0e0f'

@pytest.mark.parametrize('source,line',[
    (0xa0010000,-2147483648),  # Minor errors are never captured as SDK faults.
    (0xa0000001,-2147483648),(0xa0ff1234,-2147483648),
    (0xa0000000,0),(0xa0ff0000,-1),
    (0xa1001234,91),(0xa1011234,91),(0xa1021234,91),(0xa1fe1234,91),
    (0xa2ff1234,91),(0x00ff0000,-2147483648),(0xffff0000,-2147483648),
])
def test_unrecognized_sdk_tags_retain_checked_error_interpretation(source,line):
    decoded=decode_record(tagged_record(source,line))
    assert decoded['kind']=='checked_error'
    assert decoded['source']==source and decoded['line']==line
    assert 'severity' not in decoded and 'original_location_present' not in decoded
    assert 'original_file_id' not in decoded and 'original_line' not in decoded

def test_sdk_source_tag_does_not_reclassify_asserts():
    data=bytearray(tagged_record(0xa0ff0000,-2147483648))
    struct.pack_into('<II',data,32,6,1)
    struct.pack_into('<I',data,120,zlib.crc32(data[:120]))
    decoded=decode_record(bytes(data))
    assert decoded['kind']=='assert' and 'severity' not in decoded

@pytest.mark.parametrize('offset,fmt,value',[
    (4,'H',2),(6,'H',127),(8,'I',0),(32,'I',10),
    (32,'I',30),(32,'I',0x4000e),(112,'I',1),(124,'I',0),
])
def test_sdk_tags_do_not_relax_record_admission(offset,fmt,value):
    data=bytearray(tagged_record(0xa0ff0000,-2147483648))
    struct.pack_into('<'+fmt,data,offset,value)
    struct.pack_into('<I',data,120,zlib.crc32(data[:120]))
    with pytest.raises(ValueError):decode_record(bytes(data))

@pytest.mark.parametrize('length',[127,129])
def test_sdk_tags_still_require_exact_record_length(length):
    data=tagged_record(0xa0ff0000,-2147483648)
    with pytest.raises(ValueError):decode_record((data+bytes(1))[:length])

def test_sdk_tags_still_require_valid_crc():
    data=bytearray(tagged_record(0xa0ff0000,-2147483648));data[44]^=1
    with pytest.raises(ValueError):decode_record(bytes(data))

def test_sdk_error_decodes_from_exported_chunks():
    raw=tagged_record(0xa1ff1234,-25)+bytes(128)
    chunks={f'fault_diagnostic_{i}':raw[i*32:(i+1)*32].hex() for i in range(8)}
    decoded=decode_chunks(chunks)['records'][0]
    assert decoded['slot']==0 and decoded['kind']=='sdk_error'
    assert decoded['original_file_id']==0x1234 and decoded['original_line']==-25

@pytest.mark.parametrize('offset',[0,4,6,32,44,120,124])
def test_corruption_never_becomes_a_diagnosed_fault(offset):
    b=bytearray(record());b[offset]^=1
    with pytest.raises(ValueError):decode_record(bytes(b))

def test_absent_and_incomplete_chunks_are_distinct():
    with pytest.raises(ValueError):decode_chunks({})
    d={f'fault_diagnostic_{i}':'00'*32 for i in range(8)}
    assert decode_chunks(d)['records']==[]
    raw=record()+bytes(128)
    d={f'fault_diagnostic_{i}':raw[i*32:(i+1)*32].hex() for i in range(8)}
    assert decode_chunks(d)['records'][0]['error']==-17

def test_chunks_from_different_boots_are_not_joined_into_one_crash():
    cause=record();abort=bytearray(record())
    struct.pack_into('<II',abort,8,2,99)
    struct.pack_into('<II',abort,32,1008,3)
    abort[44:56]=bytes(12)
    struct.pack_into('<I',abort,120,zlib.crc32(abort[:120]))
    raw=cause+abort
    chunks={f'fault_diagnostic_{i}':raw[i*32:(i+1)*32].hex() for i in range(8)}
    with pytest.raises(ValueError,match='Mixed'):decode_chunks(chunks)
