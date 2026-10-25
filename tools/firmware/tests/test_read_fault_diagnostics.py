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
    assert decoded['error']==-17 and decoded['source']==2 and decoded['line']==914
    assert decoded['matches_expected_build'] is True
    assert decode_record(record(),b'x'*16)['matches_expected_build'] is False

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
