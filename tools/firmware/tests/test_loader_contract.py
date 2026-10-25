"""Independent anchor fixtures, actual OpenSSL SHA256, no hardware or keys."""
import ctypes as c
import hashlib
from pathlib import Path
import struct
import subprocess
import zlib

import pytest

ROOT=Path(__file__).resolve().parents[3]
CORE=ROOT/'firmware/loader_contract'
DOMAIN=b'VIMAR30805-LOADER-CODE44K-ANCHOR1\0'
CODE=bytes((i*29+7)%256 for i in range(0xb000))
ERASED=hashlib.sha256(b'\xff'*4096).digest()
UICR=hashlib.sha256(b'original uicr fixture').digest()
FLASH=hashlib.sha256(b'original flash fixture').digest()

class Live(c.Structure):
 _fields_=[('part',c.c_uint32),('variant',c.c_uint32),('uid',c.c_uint32*2),
  ('flash_size',c.c_uint32),('page_size',c.c_uint32),('ram_size',c.c_uint32),('uicr_size',c.c_uint32),('uicr_sha256',c.c_uint8*32)]
class Anchor(c.Structure):
 _fields_=[('variant',c.c_uint32),('uid',c.c_uint32*2),('flash_sha256',c.c_uint8*32),('uicr_sha256',c.c_uint8*32),('table_sha256',c.c_uint8*32)]
class Record(c.Structure):
 _fields_=[('kind',c.c_int),('digest',c.c_uint8*32)]
class Authorization(c.Structure):
 _fields_=[('kind',c.c_int),('measured_digest',c.c_uint8*32),('anchor',Anchor)]
class Session(c.Structure):
 _fields_=[('anchor',Anchor),('table',c.c_uint8*8192),('initialized',c.c_bool),('accepted',c.c_bool),('writing',c.c_bool)]


def table_fixture():
 return b''.join(ERASED if 0xb0000<=i*4096<0xef000 else
  hashlib.sha256(bytes([i])*4096).digest() for i in range(256))


def fixture(uid=(0x12345678,0x90abcdef),variant=0x41414430,table=None):
 table=table_fixture() if table is None else table
 page=bytearray(b'\xff'*4096)
 struct.pack_into('<4sHH11I12s',page,0,b'VAR1',1,256,1,2,0x52840,variant,*uid,
                  0x100000,0x1000,0x40000,0x1000,0x2000,b'VIMAR30805\0\0')
 page[64:160]=FLASH+UICR+hashlib.sha256(table).digest()
 struct.pack_into('<II',page,248,zlib.crc32(page[:248]),0xa60c17ed)
 live=Live(0x52840,variant,(c.c_uint32*2)(*uid),0x100000,0x1000,0x40000,0x1000,(c.c_uint8*32).from_buffer_copy(UICR))
 anchor=Anchor(variant,(c.c_uint32*2)(*uid),(c.c_uint8*32).from_buffer_copy(FLASH),
               (c.c_uint8*32).from_buffer_copy(UICR),(c.c_uint8*32).from_buffer_copy(hashlib.sha256(table).digest()))
 return bytes(page),live,anchor,table


def records(*values):
 return (Record*len(values))(*(Record(kind,(c.c_uint8*32).from_buffer_copy(digest)) for kind,digest in values))


@pytest.fixture(scope='module')
def lib(tmp_path_factory):
 path=tmp_path_factory.mktemp('loader_contract')/'core.so'
 subprocess.run(['cc','-shared','-fPIC','-std=c11','-O1','-Wall','-Wextra','-Werror',
  '-Werror=vla','-I'+str(CORE),str(CORE/'loader_contract.c'),str(Path(__file__).with_name('loader_contract_host.c')),
  '-lcrypto','-o',str(path)],check=True,capture_output=True)
 lib=c.CDLL(str(path))
 lib.loader_anchor_encode.argtypes=[c.c_void_p,c.c_size_t,c.POINTER(Anchor)]
 lib.loader_anchor_decode.argtypes=[c.c_void_p,c.c_size_t,c.POINTER(Live),c.POINTER(Anchor)]
 lib.test_digest.argtypes=[c.c_void_p,c.c_size_t,c.c_bool,c.c_void_p]
 lib.test_authorize.argtypes=[c.c_void_p,c.c_size_t,c.POINTER(Record),c.c_size_t,c.POINTER(Live),c.POINTER(Authorization)]
 lib.loader_restore_session_init.argtypes=[c.POINTER(Session),c.POINTER(Anchor)]
 lib.loader_restore_session_reset.argtypes=[c.POINTER(Session)]
 lib.loader_restore_begin_write.argtypes=[c.POINTER(Session)]
 lib.test_table.argtypes=[c.POINTER(Session),c.c_void_p,c.c_size_t]
 lib.test_page.argtypes=[c.POINTER(Session),c.c_uint32,c.c_void_p,c.c_size_t]
 return lib


@pytest.fixture(autouse=True)
def no_faults(lib):
 lib.test_inject(0,0,0)


def decode(lib,page,live):
 out=Anchor();c.memset(c.byref(out),0xa5,c.sizeof(out))
 rc=lib.loader_anchor_decode(page,len(page),c.byref(live),c.byref(out))
 return rc,out


def test_independent_record_decodes_and_encoder_matches_fixed_wire_bytes(lib):
 page,live,anchor,_=fixture()
 rc,out=decode(lib,page,live)
 assert rc==0 and bytes(out)==bytes(anchor)
 encoded=c.create_string_buffer(4096)
 assert lib.loader_anchor_encode(encoded,4096,c.byref(anchor))==0
 assert encoded.raw==page


@pytest.mark.parametrize('length',[0,1,255,256,4095,4097])
def test_record_exact_page_size_required(lib,length):
 page,live,_,_=fixture();page=(page+b'\xff'*4097)[:length]
 rc,out=decode(lib,page,live)
 assert rc<0 and bytes(out)==bytes(c.sizeof(out))


@pytest.mark.parametrize('offset',[0,4,6,8,12,16,20,24,28,32,36,40,44,48,52,62,96,160,247,248,252,253,254,255,256,4095])
def test_corrupt_torn_and_reserved_record_bytes_rejected(lib,offset):
 page,live,_,_=fixture();page=bytearray(page);page[offset]^=1
 # Recompute CRC to isolate all semantic/header checks from integrity rejection.
 if offset<248:struct.pack_into('<I',page,248,zlib.crc32(page[:248]))
 rc,out=decode(lib,bytes(page),live)
 assert rc<0 and bytes(out)==bytes(c.sizeof(out))


@pytest.mark.parametrize('field',['part','variant','uid0','uid1','flash_size','page_size','ram_size','uicr_size','uicr_sha256'])
def test_live_hardware_identity_geometry_and_uicr_must_match(lib,field):
 page,live,_,_=fixture()
 if field=='uicr_sha256':live.uicr_sha256[0]^=1
 elif field.startswith('uid'):live.uid[int(field[-1])]^=1
 else:setattr(live,field,getattr(live,field)^1)
 assert decode(lib,page,live)[0]<0


def test_real_openssl_domain_and_legacy_digests_match_independent_hashlib(lib):
 page,_,_,_=fixture();raw=CODE+page;out=c.create_string_buffer(32)
 assert lib.test_digest(raw,len(raw),True,out)==0
 assert out.raw==hashlib.sha256(DOMAIN+CODE).digest()
 assert lib.test_digest(raw,len(raw),False,out)==0
 assert out.raw==hashlib.sha256(raw).digest()


def test_two_units_share_family_authority_but_have_distinct_anchors_and_legacy_hashes(lib):
 family=hashlib.sha256(DOMAIN+CODE).digest();allowed=records((2,family))
 old_hashes=[]
 for uid in [(0x12345678,0x90abcdef),(0x11223344,0x55667788)]:
  page,live,anchor,_=fixture(uid);raw=CODE+page;old_hashes.append(hashlib.sha256(raw).digest())
  out=Authorization()
  assert lib.test_authorize(raw,len(raw),allowed,1,c.byref(live),c.byref(out))==0
  assert out.kind==2 and bytes(out.anchor)==bytes(anchor) and bytes(out.measured_digest)==family
 assert old_hashes[0]!=old_hashes[1]


@pytest.mark.parametrize('damage',['codefirst','codelast','anchor','unknown_family','truncated','unknown_kind','empty'])
def test_no_unknown_loader_or_blind_mask_acceptance(lib,damage):
 page,live,_,_=fixture();raw=bytearray(CODE+page)
 allowed=records((2,hashlib.sha256(DOMAIN+CODE).digest()))
 if damage=='codefirst':raw[0]^=1
 if damage=='codelast':raw[0xafff]^=1
 if damage=='anchor':raw[0xb018]^=1
 if damage=='unknown_family':allowed=records((2,b'\0'*32))
 if damage=='truncated':raw=raw[:-1]
 if damage=='unknown_kind':allowed[0].kind=99
 out=Authorization();c.memset(c.byref(out),0xa5,c.sizeof(out))
 assert lib.test_authorize(bytes(raw),len(raw),allowed,0 if damage=='empty' else 1,c.byref(live),c.byref(out))<0
 assert bytes(out)==bytes(c.sizeof(out))


def test_explicit_legacy_full_hash_keeps_exact_authority_without_anchor_requirement(lib):
 _,live,_,_=fixture();raw=CODE+b'\xa5'*4096
 digest=hashlib.sha256(raw).digest();allowed=records((1,digest),(2,b'\0'*32));out=Authorization()
 assert lib.test_authorize(raw,len(raw),allowed,2,c.byref(live),c.byref(out))==0
 assert out.kind==1 and bytes(out.anchor)==bytes(c.sizeof(Anchor))
 damaged=raw[:-1]+bytes([raw[-1]^1])
 assert lib.test_authorize(damaged,len(damaged),allowed,2,c.byref(live),c.byref(out))<0


def test_hash_and_reader_failure_fail_closed_and_release_crypto(lib):
 page,_,_,_=fixture();raw=CODE+page;out=c.create_string_buffer(32)
 assert lib.test_digest(raw,len(raw),True,out)==0
 steps=lib.test_steps()
 for step in range(1,steps+1):
  lib.test_inject(step,0,0)
  assert lib.test_digest(raw,len(raw),True,out)==-5
  assert out.raw==b'\0'*32 and lib.test_aborts()==1
 for off in [0,255,256,0xafff]:
  lib.test_inject(0,1,off)
  assert lib.test_digest(raw,len(raw),True,out)==-5
  assert out.raw==b'\0'*32 and lib.test_aborts()==1


def test_restore_table_is_anchored_owned_and_frozen_after_writes_begin(lib):
 _,_,anchor,table=fixture();session=Session()
 assert lib.loader_restore_session_init(c.byref(session),c.byref(anchor))==0
 assert lib.loader_restore_begin_write(c.byref(session))<0
 assert lib.test_page(c.byref(session),0x12000,bytes([0x12])*4096,4096)<0
 storage=c.create_string_buffer(table)
 assert lib.test_table(c.byref(session),storage,len(table))==0
 storage[0]=b'\0' # accepted bytes are owned by the session, not caller memory.
 assert bytes(session.table)==table
 assert lib.loader_restore_begin_write(c.byref(session))==0
 assert lib.test_page(c.byref(session),0x12000,bytes([0x12])*4096,4096)==0
 assert lib.test_table(c.byref(session),table,len(table))<0
 lib.loader_restore_session_reset(c.byref(session))
 assert bytes(session)==bytes(c.sizeof(session))
 assert lib.loader_restore_begin_write(c.byref(session))<0
 assert lib.test_table(c.byref(session),table,len(table))<0


@pytest.mark.parametrize('damage',['short','long','changed','scratch_not_ff'])
def test_wrong_table_or_unsupported_original_scratch_rejected_before_authority(lib,damage):
 table=bytearray(table_fixture())
 if damage=='scratch_not_ff':table[0xb0*32]^=1
 _,_,anchor,_=fixture(table=bytes(table) if damage=='scratch_not_ff' else None)
 session=Session();assert lib.loader_restore_session_init(c.byref(session),c.byref(anchor))==0
 if damage=='short':table=table[:-1]
 if damage=='long':table+=b'\0'
 if damage=='changed':table[0]^=1
 assert lib.test_table(c.byref(session),bytes(table),len(table))<0
 assert not session.accepted and not session.writing
 assert lib.loader_restore_begin_write(c.byref(session))<0


@pytest.mark.parametrize('address,size,changed',[(0x12001,4096,False),(0x100000,4096,False),
 (0xb0000,4096,False),(0xee000,4096,False),(0x12000,4095,False),(0x12000,4096,True)])
def test_page_helper_rejects_bad_bounds_scratch_or_payload(lib,address,size,changed):
 _,_,anchor,table=fixture();session=Session()
 assert lib.loader_restore_session_init(c.byref(session),c.byref(anchor))==0
 assert lib.test_table(c.byref(session),table,len(table))==0
 page=bytearray(bytes([0x12])*4096)
 if changed:page[0]^=1
 assert lib.test_page(c.byref(session),address,bytes(page),size)<0


def test_every_page_boundary_including_original_boot_ram_pages(lib):
 _,_,anchor,table=fixture();session=Session()
 assert lib.loader_restore_session_init(c.byref(session),c.byref(anchor))==0
 assert lib.test_table(c.byref(session),table,len(table))==0
 for index in range(256):
  rc=lib.test_page(c.byref(session),index*4096,bytes([index])*4096,4096)
  assert (rc<0)==(0xb0<=index<0xef)


def test_in_place_table_acceptance_and_invalid_retry_drop_prior_authority(lib):
 _,_,anchor,table=fixture();session=Session()
 assert lib.loader_restore_session_init(c.byref(session),c.byref(anchor))==0
 c.memmove(session.table,table,len(table))
 assert lib.test_table(c.byref(session),session.table,len(table))==0
 assert bytes(session.table)==table
 assert lib.test_table(c.byref(session),table,len(table)-1)<0
 assert not session.accepted and bytes(session.table)==b'\0'*8192


def test_failed_reinitialize_cannot_retain_prior_authority(lib):
 _,_,anchor,table=fixture();session=Session()
 assert lib.loader_restore_session_init(c.byref(session),c.byref(anchor))==0
 assert lib.test_table(c.byref(session),table,len(table))==0
 assert lib.loader_restore_begin_write(c.byref(session))==0
 assert lib.loader_restore_session_init(c.byref(session),None)<0
 assert bytes(session)==bytes(c.sizeof(session))


def test_table_crypto_failures_always_clear_unaccepted_bytes(lib):
 _,_,anchor,table=fixture();session=Session()
 assert lib.loader_restore_session_init(c.byref(session),c.byref(anchor))==0
 assert lib.test_table(c.byref(session),table,len(table))==0
 steps=lib.test_steps()
 for step in range(1,steps+1):
  lib.test_inject(step,0,0)
  assert lib.test_table(c.byref(session),table,len(table))==-5
  assert not session.accepted and not session.writing
  assert bytes(session.table)==b'\0'*8192
  assert lib.test_aborts()>=1


@pytest.mark.parametrize('offset',[0xb000,0xb0ff,0xb100,0xbfff])
def test_anchor_reader_failure_never_publishes_authorization(lib,offset):
 page,live,_,_=fixture();raw=CODE+page
 allowed=records((2,hashlib.sha256(DOMAIN+CODE).digest()));out=Authorization()
 lib.test_inject(0,1,offset)
 assert lib.test_authorize(raw,len(raw),allowed,1,c.byref(live),c.byref(out))==-5
 assert bytes(out)==bytes(c.sizeof(out))


@pytest.mark.parametrize('kind,digest_kind',[(1,'family'),(2,'legacy'),(1,'unknown')])
def test_compatibility_record_types_never_reinterpret_another_digest(lib,kind,digest_kind):
 page,live,_,_=fixture();raw=CODE+page
 digest={'family':hashlib.sha256(DOMAIN+CODE).digest(),
         'legacy':hashlib.sha256(raw).digest(),'unknown':b'\0'*32}[digest_kind]
 allowed=records((kind,digest));out=Authorization()
 assert lib.test_authorize(raw,len(raw),allowed,1,c.byref(live),c.byref(out))<0


@pytest.mark.parametrize('committed',[0,1,2,3])
def test_commit_word_is_written_last_and_partial_commit_never_decodes(lib,committed):
 page,live,_,_=fixture();page=bytearray(page)
 marker=page[252:256];page[252:256]=b'\xff'*4
 page[252:252+committed]=marker[:committed]
 assert decode(lib,bytes(page),live)[0]<0


@pytest.mark.parametrize('family,size',[(True,0xafff),(False,0xbfff)])
def test_hash_span_is_fixed_and_truncation_rejected(lib,family,size):
 out=c.create_string_buffer(32)
 assert lib.test_digest((CODE+b'\xff'*4096)[:size],size,family,out)<0
 assert out.raw==b'\0'*32


def test_invalid_and_null_inputs_fail_closed(lib):
 page,live,anchor,table=fixture();out=Anchor()
 assert lib.loader_anchor_decode(None,4096,c.byref(live),c.byref(out))<0
 assert lib.loader_anchor_decode(page,4096,None,c.byref(out))<0
 assert lib.loader_anchor_decode(page,4096,c.byref(live),None)<0
 assert lib.loader_anchor_encode(None,4096,c.byref(anchor))<0
 assert lib.loader_anchor_encode(c.create_string_buffer(4096),4095,c.byref(anchor))<0
 bad=Anchor();assert lib.loader_anchor_encode(c.create_string_buffer(4096),4096,c.byref(bad))<0
 outbuf=c.create_string_buffer(32)
 assert lib.test_digest(page,len(page),True,outbuf)<0
 assert lib.loader_restore_session_init(None,c.byref(anchor))<0
 lib.loader_restore_session_reset(None)
 assert lib.loader_restore_begin_write(None)<0
 assert lib.test_table(None,table,len(table))<0
 assert lib.test_page(None,0,page,len(page))<0


def test_error_attempt_cannot_replace_table_after_write_lock(lib):
 _,_,anchor,table=fixture();session=Session()
 assert lib.loader_restore_session_init(c.byref(session),c.byref(anchor))==0
 assert lib.test_table(c.byref(session),table,len(table))==0
 assert lib.loader_restore_begin_write(c.byref(session))==0
 for value,size in [(None,0),(b'bad',3),(table,8192)]:
  assert lib.test_table(c.byref(session),value,size)==-16
  assert session.accepted and session.writing and bytes(session.table)==table


def test_positive_callback_results_are_errors_not_partial_success(lib):
 page,_,_,_=fixture();raw=CODE+page;out=c.create_string_buffer(32)
 assert lib.test_digest(raw,len(raw),True,out)==0
 steps=lib.test_steps()
 for step in [1,2,steps]:
  lib.test_inject(-step,0,0)
  assert lib.test_digest(raw,len(raw),True,out)==-5
  assert out.raw==b'\0'*32 and lib.test_aborts()==1
 lib.test_inject(0,2,0)
 assert lib.test_digest(raw,len(raw),True,out)==-5
 assert out.raw==b'\0'*32 and lib.test_aborts()==1


@pytest.mark.parametrize('operation',['decode','authorize'])
def test_output_alias_cannot_erase_genuine_live_uicr_before_comparison(lib,operation):
 # Independently forge a CRC-valid record with an incorrect zero UICR digest.
 # The output starts at the REAL live UICR field: eager output zeroing used to
 # erase the trusted expected digest and turn this mismatch into acceptance.
 page,live,_,_=fixture();page=bytearray(page);page[96:128]=b'\0'*32
 struct.pack_into('<I',page,248,zlib.crc32(page[:248]))
 workspace=c.create_string_buffer(256)
 c.memmove(workspace,c.byref(live),c.sizeof(live))
 live_pointer=c.cast(workspace,c.POINTER(Live))
 offset=Live.uicr_sha256.offset
 assert offset==32 and bytes(live_pointer.contents.uicr_sha256)==UICR
 if operation=='decode':
  out=c.cast(c.byref(workspace,offset),c.POINTER(Anchor))
  rc=lib.loader_anchor_decode(bytes(page),len(page),live_pointer,out)
 else:
  allowed=records((2,hashlib.sha256(DOMAIN+CODE).digest()))
  out=c.cast(c.byref(workspace,offset),c.POINTER(Authorization))
  raw=CODE+bytes(page)
  rc=lib.test_authorize(raw,len(raw),allowed,len(allowed),live_pointer,out)
 assert rc==-13
 assert bytes(out.contents)==bytes(c.sizeof(out.contents))


def test_decoder_output_may_alias_source_page_after_all_checks(lib):
 page,live,anchor,_=fixture();storage=c.create_string_buffer(page)
 out=c.cast(c.byref(storage,96),c.POINTER(Anchor))
 assert lib.loader_anchor_decode(storage,4096,c.byref(live),out)==0
 assert bytes(out.contents)==bytes(anchor)


@pytest.mark.parametrize('overlap',['code','anchor','records','live'])
def test_authorizer_stages_result_until_aliased_inputs_are_consumed(lib,overlap):
 page,live,anchor,_=fixture();raw=CODE+page
 source=c.create_string_buffer(raw)
 allowed=records((2,hashlib.sha256(DOMAIN+CODE).digest()))
 record_workspace=c.create_string_buffer(c.sizeof(Authorization)+c.sizeof(Record))
 c.memmove(record_workspace,allowed,c.sizeof(allowed))
 record_pointer=c.cast(record_workspace,c.POINTER(Record))
 live_workspace=c.create_string_buffer(256)
 c.memmove(live_workspace,c.byref(live),c.sizeof(live))
 live_pointer=c.cast(live_workspace,c.POINTER(Live))
 if overlap in ['code','anchor']:
  out=c.cast(c.byref(source,0 if overlap=='code' else 0xb000),c.POINTER(Authorization))
 elif overlap=='records':out=c.cast(record_workspace,c.POINTER(Authorization))
 else:out=c.cast(live_workspace,c.POINTER(Authorization))
 assert lib.test_authorize(source,len(raw),record_pointer,1,live_pointer,out)==0
 assert out.contents.kind==2
 assert bytes(out.contents.anchor)==bytes(anchor)
 assert bytes(out.contents.measured_digest)==hashlib.sha256(DOMAIN+CODE).digest()


@pytest.mark.parametrize('family',[False,True])
def test_stream_digest_publishes_after_reading_aliased_source(lib,family):
 page,_,_,_=fixture();raw=CODE+page;storage=c.create_string_buffer(raw)
 out=c.cast(storage,c.c_void_p)
 expected=hashlib.sha256(DOMAIN+CODE if family else raw).digest()
 assert lib.test_digest(storage,len(raw),family,out)==0
 assert storage.raw[:32]==expected
