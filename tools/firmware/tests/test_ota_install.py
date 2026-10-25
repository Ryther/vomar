"""Installer fault injection uses real signatures and SDK decoder, RAM-backed flash."""
import ctypes
import hashlib
import pytest
from test_ota_image import lib, fixture, Info

class Tx(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint32) for n in ['format_version','generation','state','stage_start','stage_end','candidate_size','signed_image_size']] + [('candidate_digest',ctypes.c_uint8*32),('final_digest',ctypes.c_uint8*32),('second_start',ctypes.c_uint32),('second_end',ctypes.c_uint32),('recovery_digest',ctypes.c_uint8*32),('loader_digest',ctypes.c_uint8*32)]
ERASE=ctypes.CFUNCTYPE(ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_size_t)
WRITE=ctypes.CFUNCTYPE(ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_size_t)
SAVE=ctypes.CFUNCTYPE(ctypes.c_int,ctypes.c_void_p,ctypes.POINTER(Tx))
class Io(ctypes.Structure):
    _fields_=[('mapped',ctypes.c_void_p),('mapped_size',ctypes.c_size_t),('ctx',ctypes.c_void_p),('erase',ERASE),('write',WRITE),('save',SAVE),('allowed_loaders',ctypes.c_void_p),('allowed_loader_count',ctypes.c_size_t)]

def setup(lib):
    source,expected=fixture()
    memory=ctypes.create_string_buffer(b'\xff'*0x100000)
    ctypes.memmove(ctypes.addressof(memory)+0x71000,source,len(source))
    info=Info()
    assert lib.ota_image_validate(source,len(source),0x65000,ctypes.byref(info))==0
    tx=Tx(1,1,2,0x71000,0xae000,len(source),len(expected))
    tx.candidate_digest[:]=info.source_digest
    tx.final_digest[:]=info.signed_digest
    lib.ota_install_run.argtypes=[ctypes.POINTER(Tx),ctypes.POINTER(Io)]
    return memory,tx,expected

def install(lib,memory,tx,fail_page=None,fail_save=None,corrupt_readback=False,fail_write=None,allowlist=True):
    erases=[]; saves=[]
    @ERASE
    def erase(ctx,address,size):
        assert address>=0xc000 and address+size<=tx.stage_start
        assert size==4096 and address%4096==0
        erases.append(address)
        if address==fail_page: return -5
        ctypes.memset(ctypes.addressof(memory)+address,255,size)
        return 0
    @WRITE
    def write(ctx,address,data,size):
        assert address>=0xc000 and address+size<=tx.stage_start
        if address==fail_write:
            ctypes.memmove(ctypes.addressof(memory)+address,data,size//2)
            return -5
        ctypes.memmove(ctypes.addressof(memory)+address,data,size)
        if corrupt_readback: memory[address]=bytes([memory[address][0]^1])
        return 0
    @SAVE
    def save(ctx,record):
        saves.append(record.contents.state)
        return -5 if record.contents.state==fail_save else 0
    allowed=ctypes.create_string_buffer(hashlib.sha256(b"\xff"*0xc000).digest())
    io=Io(ctypes.addressof(memory),len(memory),None,erase,write,save,ctypes.addressof(allowed),1 if allowlist else 0)
    rc=lib.ota_install_run(ctypes.byref(tx),ctypes.byref(io))
    return rc,erases,saves

def test_install_signed_image(lib):
    memory,tx,expected=setup(lib)
    assert install(lib,memory,tx)[0]==1
    assert bytes(memory[0xc000:0xc000+len(expected)])==expected
    assert tx.state==4

@pytest.mark.parametrize('invalid', ['source','final_digest','candidate_digest','size','overlap','generation'])
def test_invalid_candidate_never_erases(lib,invalid):
    memory,tx,expected=setup(lib)
    if invalid=='source': memory[tx.stage_start+520]=b'X'
    if invalid=='final_digest': tx.final_digest[0]^=1
    if invalid=='candidate_digest': tx.candidate_digest[0]^=1
    if invalid=='size': tx.signed_image_size+=1
    if invalid=='overlap': tx.stage_start=0xc000
    if invalid=='generation': tx.generation=0xffffffff
    rc,erases,saves=install(lib,memory,tx)
    assert rc<0 and not erases and not saves

@pytest.mark.parametrize('operation', ['erase','write'])
def test_page_failures_restart_without_source_damage(lib,operation):
    memory,tx,expected=setup(lib)
    for page in range(0xc000,0xc000+len(expected),4096):
        memory,tx,expected=setup(lib)
        before=bytes(memory[tx.stage_start:tx.stage_end])
        rc,_,saves=install(lib,memory,tx,**({'fail_page':page} if operation=='erase' else {'fail_write':page}))
        assert rc==-5 and saves==[3]
        assert bytes(memory[tx.stage_start:tx.stage_end])==before
        assert install(lib,memory,tx)[0]==1
        assert bytes(memory[0xc000:0xc000+len(expected)])==expected

def test_pending_record_persist_failure_no_erase(lib):
    memory,tx,expected=setup(lib)
    rc,erases,_=install(lib,memory,tx,fail_save=3)
    assert rc==-5 and erases==[]

def test_completed_primary_after_lost_final_journal_no_reerase(lib):
    memory,tx,expected=setup(lib)
    assert install(lib,memory,tx,fail_save=4)[0]==-5
    assert tx.state==3
    rc,erases,saves=install(lib,memory,tx)
    assert rc==1 and not erases and saves==[4]

def test_readback_failure_stays_installing(lib):
    memory,tx,expected=setup(lib)
    rc,_,saves=install(lib,memory,tx,corrupt_readback=True)
    assert rc<0 and tx.state==3 and saves==[3]

@pytest.mark.parametrize('version',[(0,6,1,4),(0,6,1,5),(0,7,0,0),(1,0,0,0)])
@pytest.mark.parametrize('target',[None,b'VIMAR30805\x01'])
def test_stale_candidate_rejected_against_authenticated_primary(lib,version,target):
    memory,tx,_=setup(lib)
    _,primary=fixture(payload=b'current application'*5000,version=version,target=target)
    ctypes.memmove(ctypes.addressof(memory)+0xc000,primary,len(primary))
    rc,erases,saves=install(lib,memory,tx)
    assert rc<0 and erases==[] and saves==[]

def test_newer_version_allowed_against_valid_primary(lib):
    memory,tx,_=setup(lib)
    _,primary=fixture(version=(0,6,1,3),target=None)
    ctypes.memmove(ctypes.addressof(memory)+0xc000,primary,len(primary))
    assert install(lib,memory,tx)[0]==1

@pytest.mark.parametrize('crypto_error',[-5,-12,-95])
def test_primary_crypto_operational_errors_fail_closed(lib,crypto_error):
    memory,tx,_=setup(lib)
    _,primary=fixture(version=(1,0,0,0),target=None)
    ctypes.memmove(ctypes.addressof(memory)+0xc000,primary,len(primary))
    lib.ota_test_primary_error(crypto_error)
    try:
        rc,erases,saves=install(lib,memory,tx)
        assert rc==crypto_error and erases==[] and saves==[]
    finally:
        lib.ota_test_primary_error(0)

# Profile2 uses the actual signed recovery, a pinned loader allowlist and a
# random-looking payload spanning both sources. Missing checks can erase code.
def split_setup(lib):
    import random,struct
    from test_ota_image import Reader,WRITE as IMAGE_WRITE
    payload=random.Random(23).randbytes(260000)
    source,expected=fixture(payload=payload,target=b'VIMAR30805\x02')
    memory=ctypes.create_string_buffer(b'\xff'*0x100000)
    first=0xae000-0x71000
    assert first<len(source)<first+45056
    ctypes.memmove(ctypes.addressof(memory)+0x71000,source[:first],first)
    ctypes.memmove(ctypes.addressof(memory)+0xe4000,source[first:],len(source)-first)
    recovery_payload=struct.pack('<II',0x2003f000,0xb0209)+bytes(500)
    _,recovery=fixture(payload=recovery_payload,target=None)
    ctypes.memmove(ctypes.addressof(memory)+0xb0000,recovery,len(recovery))
    info=Info()
    from test_ota_image import fragmented
    reader,callback=fragmented(source,first,2)
    lib.ota_image_validate_reader.argtypes=[ctypes.POINTER(Reader),ctypes.c_uint32,ctypes.POINTER(Info)]
    assert lib.ota_image_validate_reader(ctypes.byref(reader),0x65000,ctypes.byref(info))==0
    tx=Tx(2,1,2,0x71000,0xae000,len(source),len(expected))
    tx.second_start=0xe4000;tx.second_end=0xef000
    tx.candidate_digest[:]=info.source_digest;tx.final_digest[:]=info.signed_digest
    tx.recovery_digest[:]=hashlib.sha256(recovery).digest()
    tx.loader_digest[:]=hashlib.sha256(bytes(memory[:0xc000])).digest()
    return memory,tx,expected

def test_split_install_rechecks_recovery_loader_and_both_sources(lib):
    memory,tx,expected=split_setup(lib)
    before_a=bytes(memory[0x71000:0xae000]);before_b=bytes(memory[0xe4000:0xef000])
    rc,_,_=install(lib,memory,tx)
    assert rc==1
    assert bytes(memory[0xc000:0xc000+len(expected)])==expected
    assert bytes(memory[0x71000:0xae000])==before_a and bytes(memory[0xe4000:0xef000])==before_b

@pytest.mark.parametrize('damage',['loader','forged_loader_binding','recovery','source_second','binding','no_allowlist'])
def test_split_mismatch_fails_before_any_mutation(lib,damage):
    memory,tx,_=split_setup(lib)
    if damage=='loader':memory[7]=b'X'
    if damage=='recovery':memory[0xb0210]=b'X'
    if damage=='source_second':memory[0xe4010]=b'X'
    if damage=='binding':tx.recovery_digest[0]^=1
    if damage=='forged_loader_binding':
        memory[7]=b'X';tx.loader_digest[:]=hashlib.sha256(bytes(memory[:0xc000])).digest()
    rc,erases,saves=install(lib,memory,tx,allowlist=damage!='no_allowlist')
    assert rc<0 and erases==[] and saves==[]

@pytest.mark.parametrize('operation',['erase','write'])
def test_split_every_primary_page_interruption_replays_without_source_damage(lib,operation):
    memory,tx,expected=split_setup(lib)
    initial=bytes(memory)
    for page in range(0xc000,0xc000+len(expected),4096):
        ctypes.memmove(memory,initial,len(initial));tx.state=2;tx.generation=1
        rc,_,_=install(lib,memory,tx,**({'fail_page':page} if operation=='erase' else {'fail_write':page}))
        assert rc==-5
        assert bytes(memory[0x71000:0xae000])==initial[0x71000:0xae000]
        assert bytes(memory[0xe4000:0xef000])==initial[0xe4000:0xef000]
        assert install(lib,memory,tx)[0]==1
        assert bytes(memory[0xc000:0xc000+len(expected)])==expected

@pytest.mark.parametrize('pending_profile,current_profile',[(1,2),(2,1)])
@pytest.mark.parametrize('version',[(9,0,0,0),(0,0,1,0)])
def test_authentic_opposite_profile_primary_is_never_treated_as_interrupted(lib,pending_profile,current_profile,version):
    memory,tx,_=(setup(lib) if pending_profile==1 else split_setup(lib))
    _,current=fixture(version=version,target=b'VIMAR30805'+bytes([current_profile]))
    ctypes.memmove(ctypes.addressof(memory)+0xc000,current,len(current))
    rc,erases,saves=install(lib,memory,tx)
    assert rc<0 and erases==[] and saves==[]

@pytest.fixture(scope='module')
def split_lib(tmp_path_factory):
    from test_ota_image import build_test_library
    return build_test_library(tmp_path_factory,split=True)

@pytest.mark.parametrize('state',[1,2,3,4])
def test_native_split_profile_rejects_v1_even_when_primary_erased(split_lib,state):
    import errno
    memory,tx,_=setup(split_lib);tx.state=state;before=bytes(memory)
    rc,erases,saves=install(split_lib,memory,tx)
    assert rc==-errno.EPROTONOSUPPORT and erases==[] and saves==[] and bytes(memory)==before

def test_native_split_profile_still_installs_v2(split_lib):
    setup(split_lib)
    memory,tx,expected=split_setup(split_lib)
    assert install(split_lib,memory,tx)[0]==1
    assert bytes(memory[0xc000:0xc000+len(expected)])==expected
