"""Opt-in typed runtime snapshot; independently constructed anchors and real SHA."""
import ctypes as c
import hashlib
from pathlib import Path
import subprocess
import zlib
import struct
import pytest
from test_loader_contract import Live, Record, CODE, DOMAIN, fixture, records
ROOT=Path(__file__).resolve().parents[3]
CORE=ROOT/'firmware/loader_contract'

class Snapshot(c.Structure):
 _fields_=[('uid',c.c_uint32*2),('kind',c.c_int),('digest',c.c_uint8*32),('anchor_sha256',c.c_uint8*32)]

@pytest.fixture(scope='module')
def lib(tmp_path_factory):
 d=tmp_path_factory.mktemp('loader_runtime');source=d/'host.c'
 source.write_text('#include "'+str(ROOT/'tools/firmware/tests/loader_contract_host.c')+'"\n#include "loader_runtime.h"\n'+r'''
int runtime_snapshot(const uint8_t*p,size_t n,const struct loader_contract_record*k,size_t count,const struct loader_contract_live*l,struct loader_runtime_identity*out){
 struct memory m={p,n};struct loader_contract_reader r={.ctx=&m,.size=n,.read=read_memory};return loader_runtime_snapshot(&r,k,count,l,&hash,out);
}
''')
 library=d/'runtime.so';subprocess.run(['cc','-shared','-fPIC','-std=c11','-O1','-Wall','-Wextra','-Werror','-fsanitize=undefined','-fno-sanitize-recover=all','-I'+str(CORE),str(CORE/'loader_contract.c'),str(CORE/'loader_runtime.c'),str(source),'-lcrypto','-o',str(library)],check=True,capture_output=True)
 lib=c.CDLL(str(library));lib.runtime_snapshot.argtypes=[c.c_void_p,c.c_size_t,c.POINTER(Record),c.c_size_t,c.POINTER(Live),c.POINTER(Snapshot)];return lib

@pytest.fixture(autouse=True)
def clean_faults(lib):lib.test_inject(0,0,0)

def snapshot(lib,raw,allowed,live):
 out=Snapshot();c.memset(c.byref(out),0xa5,c.sizeof(out));rc=lib.runtime_snapshot(raw,len(raw),allowed,len(allowed),c.byref(live),c.byref(out));return rc,out

def test_two_live_units_share_only_explicit_family_and_distinct_validated_anchor_measurements(lib):
 allowed=records((2,hashlib.sha256(DOMAIN+CODE).digest()));anchors=[]
 for uid in [(0x12345678,0x90abcdef),(0x11223344,0x55667788)]:
  page,live,_,_=fixture(uid);rc,out=snapshot(lib,CODE+page,allowed,live)
  assert rc==0 and list(out.uid)==list(uid) and out.kind==2
  assert bytes(out.digest)==hashlib.sha256(DOMAIN+CODE).digest()
  assert bytes(out.anchor_sha256)==hashlib.sha256(page).digest();anchors.append(bytes(out.anchor_sha256))
 assert anchors[0]!=anchors[1]

def test_legacy_full_hash_remains_typed_and_never_grants_common_anchor_status(lib):
 _,live,_,_=fixture();raw=CODE+bytes([0xa5])*4096;digest=hashlib.sha256(raw).digest()
 rc,out=snapshot(lib,raw,records((1,digest)),live)
 assert rc==0 and out.kind==1 and bytes(out.digest)==digest and bytes(out.anchor_sha256)==bytes(32)
 assert snapshot(lib,raw,records((2,digest)),live)[0]<0

@pytest.mark.parametrize('damage',['unknownkind','unknownfamily','code','commit','uid','uicr','geometry','reserved','truncated','overlong'])
def test_unknown_torn_mismatched_live_or_nonfixed_span_fails_closed(lib,damage):
 page,live,_,_=fixture();raw=bytearray(CODE+page);allowed=records((2,hashlib.sha256(DOMAIN+CODE).digest()))
 if damage=='unknownkind':allowed[0].kind=99
 if damage=='unknownfamily':allowed[0].digest[0]^=1
 if damage=='code':raw[0xafff]^=1
 if damage=='commit':raw[0xb0fc]^=1
 if damage=='uid':live.uid[0]^=1
 if damage=='uicr':live.uicr_sha256[0]^=1
 if damage=='geometry':live.ram_size//=2
 if damage=='reserved':raw[0xb100]=0
 if damage=='truncated':raw=raw[:-1]
 if damage=='overlong':raw+=b'\xff'
 rc,out=snapshot(lib,bytes(raw),allowed,live);assert rc<0 and bytes(out)==bytes(c.sizeof(out))

def test_alias_of_live_uicr_cannot_erase_expected_hash_before_admission(lib):
 page,live,_,_=fixture();page=bytearray(page);page[96:128]=bytes(32);struct.pack_into('<I',page,248,zlib.crc32(page[:248]))
 allowed=records((2,hashlib.sha256(DOMAIN+CODE).digest()))
 storage=c.create_string_buffer(32+c.sizeof(Snapshot));c.memmove(storage,c.byref(live),c.sizeof(live))
 expected=Live.from_buffer(storage);out=Snapshot.from_buffer(storage,32)
 assert lib.runtime_snapshot(CODE+page,0xc000,allowed,1,c.byref(expected),c.byref(out))<0
 assert bytes(out)==bytes(c.sizeof(out))

@pytest.mark.parametrize('target',['live','record','page'])
def test_valid_output_can_alias_consumed_inputs(lib,target):
 page,live,_,_=fixture();allowed=records((2,hashlib.sha256(DOMAIN+CODE).digest()));raw=c.create_string_buffer(CODE+page)
 expected_uid=list(live.uid)
 if target=='live':
  storage=c.create_string_buffer(max(c.sizeof(live),c.sizeof(Snapshot)));c.memmove(storage,c.byref(live),c.sizeof(live));live=Live.from_buffer(storage);out=Snapshot.from_buffer(storage)
 elif target=='record':
  storage=c.create_string_buffer(c.sizeof(Snapshot));c.memmove(storage,allowed,c.sizeof(Record));allowed=c.cast(storage,c.POINTER(Record));out=Snapshot.from_buffer(storage)
 else:out=Snapshot.from_buffer(raw,0xb000)
 assert lib.runtime_snapshot(raw,0xc000,allowed,1,c.byref(live),c.byref(out))==0
 assert list(out.uid)==expected_uid and out.kind==2 and bytes(out.anchor_sha256)==hashlib.sha256(page).digest()

def test_all_hash_failures_clean_up_and_zero_output_including_anchor_hash_phase(lib):
 page,live,_,_=fixture();raw=CODE+page;allowed=records((2,hashlib.sha256(DOMAIN+CODE).digest()))
 assert snapshot(lib,raw,allowed,live)[0]==0;steps=lib.test_steps()
 for fault in range(1,steps+1):
  lib.test_inject(fault,0,0);rc,out=snapshot(lib,raw,allowed,live)
  assert rc<0 and bytes(out)==bytes(c.sizeof(out)) and lib.test_aborts()>=1
 lib.test_inject(0,2,0xbfff);rc,out=snapshot(lib,raw,allowed,live)
 assert rc<0 and bytes(out)==bytes(c.sizeof(out))
