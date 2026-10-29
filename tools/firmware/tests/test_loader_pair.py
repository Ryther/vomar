"""Typed loader/anchor authority plus real signed RECOVERY and full-hash journal binding."""
import ctypes as c
import hashlib,struct,subprocess
from pathlib import Path
import pytest
from test_loader_contract import CODE,DOMAIN,Live,Record,fixture as anchor_fixture,records
from test_loader_runtime import Snapshot
from test_image_roles import fixture as image_fixture,Info
ROOT=Path(__file__).resolve().parents[3]

class Pair(c.Structure):
 _fields_=[('loader',Snapshot),('loader_full_sha256',c.c_uint8*32),('recovery',Info)]

@pytest.fixture(scope='module')
def crypto(tmp_path_factory):
 """Real primary-image authentication needs no compression SDK or project key."""
 import re
 from cryptography.hazmat.primitives import serialization
 from cryptography.hazmat.primitives.asymmetric import ec
 directory=tmp_path_factory.mktemp('pair_crypto');key=ec.generate_private_key(ec.SECP256R1())
 public=key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
 der=key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
 source=(ROOT/'firmware/ota/ota_image.c').read_text()
 for name,value in [('public_key',public),('public_key_hash',hashlib.sha256(der).digest())]:
  source,count=re.subn(r'(static const uint8_t '+name+r'\[\d+\] = \{).*?\};',lambda m:m[1]+','.join(hex(b)for b in value)+'};',source,count=1,flags=re.S)
  assert count==1
 path=directory/'ota_image_test_key.c';path.write_text(source)
 library=directory/'crypto.so'
 subprocess.run(['cc','-shared','-fPIC','-std=c11','-DOTA_IMAGE_AUTH_ONLY','-DOTA_IMAGE_HOST',
  '-Wno-deprecated-declarations','-I'+str(ROOT/'firmware/ota'),str(path),'-lcrypto','-o',str(library)],check=True,capture_output=True)
 return c.CDLL(str(library)),key,hashlib.sha256(der).digest()

@pytest.fixture(scope='module')
def pairlib(crypto,tmp_path_factory):
 d=tmp_path_factory.mktemp('typed_pair');source=d/'host.c'
 source.write_text('#include "'+str(ROOT/'tools/firmware/tests/loader_contract_host.c')+'"\n#include "loader_pair.h"\n'+r'''
int verify_pair(const uint8_t*loader,size_t n,const struct loader_contract_record*k,size_t count,const struct loader_contract_live*l,const uint8_t*recovery,size_t capacity,const uint8_t expected[32],struct loader_pair_result*out){
 struct memory m={loader,n};struct loader_contract_reader r={.ctx=&m,.size=n,.read=read_memory};return loader_pair_verify(&r,k,count,l,&hash,recovery,capacity,expected,out);
}
int authenticate_pair(const uint8_t*loader,size_t n,const struct loader_contract_record*k,size_t count,const struct loader_contract_live*l,const uint8_t*recovery,size_t capacity,struct loader_pair_result*out){
 struct memory m={loader,n};struct loader_contract_reader r={.ctx=&m,.size=n,.read=read_memory};return loader_pair_authenticate(&r,k,count,l,&hash,recovery,capacity,out);
}
''')
 key_source=Path(crypto[0]._name).parent/'ota_image_test_key.c';library=d/'pair.so'
 subprocess.run(['cc','-shared','-fPIC','-std=c11','-O1','-Wall','-Wextra','-Werror','-Wno-deprecated-declarations','-fsanitize=undefined',
 '-DOTA_IMAGE_AUTH_ONLY','-DOTA_IMAGE_HOST','-I'+str(ROOT/'firmware/loader_contract'),'-I'+str(ROOT/'firmware/ota'),
 str(ROOT/'firmware/loader_contract/loader_contract.c'),str(ROOT/'firmware/loader_contract/loader_runtime.c'),str(ROOT/'firmware/loader_contract/loader_pair.c'),str(ROOT/'firmware/ota/ota_pair.c'),str(key_source),str(source),'-lcrypto','-o',str(library)],check=True,capture_output=True)
 lib=c.CDLL(str(library));lib.verify_pair.argtypes=[c.c_void_p,c.c_size_t,c.POINTER(Record),c.c_size_t,c.POINTER(Live),c.c_void_p,c.c_size_t,c.c_void_p,c.POINTER(Pair)]
 lib.authenticate_pair.argtypes=lib.verify_pair.argtypes[:7]+[c.POINTER(Pair)]
 return lib

def run(lib,loader,allowed,live,recovery,expected=None):
 out=Pair();c.memset(c.byref(out),0xa5,c.sizeof(out))
 if expected is None:expected=hashlib.sha256(recovery).digest()
 rc=lib.verify_pair(loader,len(loader),allowed,len(allowed),c.byref(live),recovery,len(recovery),expected,c.byref(out));return rc,out

def test_common_authority_preserves_full48k_journal_and_distinct_recovery_hash_meanings(pairlib,crypto):
 page,live,_,_=anchor_fixture();loader=CODE+page;recovery,_=image_fixture(crypto,role=b'\x02',vector_base=0xb0000)
 family=hashlib.sha256(DOMAIN+CODE).digest();rc,out=run(pairlib,loader,records((2,family)),live,recovery)
 assert rc==0 and out.loader.kind==2 and bytes(out.loader.digest)==family
 assert bytes(out.loader_full_sha256)==hashlib.sha256(loader).digest()!=family
 end=512+struct.unpack_from('<I',recovery,12)[0]+struct.unpack_from('<H',recovery,10)[0]
 assert bytes(out.recovery.output_digest)==hashlib.sha256(recovery).digest()
 assert bytes(out.recovery.signed_digest)==hashlib.sha256(recovery[:end]).digest()!=bytes(out.recovery.output_digest)

@pytest.mark.parametrize('role',[b'\x01',b'\x03',b'\x04',b'\x05',None])
def test_other_signed_roles_never_inherit_recovery_pair_authority(pairlib,crypto,role):
 page,live,_,_=anchor_fixture();recovery,_=image_fixture(crypto,role=role,vector_base=0xb0000)
 rc,out=run(pairlib,CODE+page,records((2,hashlib.sha256(DOMAIN+CODE).digest())),live,recovery)
 assert rc<0 and bytes(out)==bytes(c.sizeof(out))

@pytest.mark.parametrize('damage',['family','anchor','uicr','filehash','signature','vectors','profile'])
def test_unknown_family_bad_live_or_authentication_never_grants_pair(pairlib,crypto,damage):
 page,live,_,_=anchor_fixture();loader=CODE+page;family=hashlib.sha256(DOMAIN+CODE).digest();allowed=records((2,family))
 recovery,_=image_fixture(crypto,role=b'\x02',vector_base=0xc000 if damage=='vectors' else 0xb0000,target=b'VIMAR30805\x01' if damage=='profile' else b'VIMAR30805\x02')
 expected=hashlib.sha256(recovery).digest()
 if damage=='family':allowed[0].digest[0]^=1
 if damage=='anchor':loader=loader[:-1]+b'\x00'
 if damage=='uicr':live.uicr_sha256[0]^=1
 if damage=='filehash':expected=bytes(32)
 if damage=='signature':recovery=recovery[:-1]+bytes([recovery[-1]^1])
 rc,out=run(pairlib,loader,allowed,live,recovery,expected)
 assert rc<0 and bytes(out)==bytes(c.sizeof(out))

def test_explicit_legacy_record_has_only_exact_full48k_authority(pairlib,crypto):
 _,live,_,_=anchor_fixture();loader=CODE+b'\xa5'*4096;full=hashlib.sha256(loader).digest();recovery,_=image_fixture(crypto,role=b'\x02',vector_base=0xb0000)
 rc,out=run(pairlib,loader,records((1,full)),live,recovery)
 assert rc==0 and out.loader.kind==1 and bytes(out.loader_full_sha256)==full and bytes(out.loader.anchor_sha256)==bytes(32)
 assert run(pairlib,loader,records((2,full)),live,recovery)[0]<0


@pytest.mark.parametrize('version',[(1,0,0,0),(1,1,1,0),(1,99,255,0)])
def test_same_recovery_contract_admits_different_versions_without_file_pins(pairlib,crypto,version):
 page,live,_,_=anchor_fixture();loader=CODE+page
 recovery,_=image_fixture(crypto,role=b'\x02',vector_base=0xb0000,version=version)
 allowed=records((2,hashlib.sha256(DOMAIN+CODE).digest()));out=Pair()
 assert pairlib.authenticate_pair(loader,len(loader),allowed,len(allowed),c.byref(live),recovery,len(recovery),c.byref(out))==0
 assert bytes(out.recovery.output_digest)==hashlib.sha256(recovery).digest()
 # Exact operation identity remains a distinct, stricter check.
 different,_=image_fixture(crypto,role=b'\x02',vector_base=0xb0000,version=version)
 assert run(pairlib,loader,allowed,live,recovery,hashlib.sha256(different).digest())[0]<0


@pytest.mark.parametrize('damage',['role','roleless','model','profile','signature','vectors','family','anchor','uicr'])
def test_contract_admission_still_requires_complete_authenticated_recovery_and_loader(pairlib,crypto,damage):
 page,live,_,_=anchor_fixture();loader=CODE+page
 target={'model':b'WRONG30805\x02','profile':b'VIMAR30805\x01'}.get(damage,b'VIMAR30805\x02')
 role=None if damage=='roleless' else b'\x01' if damage=='role' else b'\x02'
 recovery,_=image_fixture(crypto,role=role,target=target,vector_base=0xc000 if damage=='vectors' else 0xb0000)
 allowed=records((2,hashlib.sha256(DOMAIN+CODE).digest()))
 if damage=='signature':recovery=recovery[:-1]+bytes([recovery[-1]^1])
 if damage=='family':allowed[0].digest[0]^=1
 if damage=='anchor':loader=loader[:-1]+b'\x00'
 if damage=='uicr':live.uicr_sha256[0]^=1
 out=Pair();c.memset(c.byref(out),0xa5,c.sizeof(out))
 assert pairlib.authenticate_pair(loader,len(loader),allowed,len(allowed),c.byref(live),recovery,len(recovery),c.byref(out))<0
 assert bytes(out)==bytes(c.sizeof(out))


@pytest.mark.parametrize('version',[(1,0,0,0),(1,1,1,0),(1,99,255,0)])
def test_legacy_loader_admits_same_signed_contract_without_a_recovery_pin(pairlib,crypto,version):
 recovery,_=image_fixture(crypto,role=b'\x02',vector_base=0xb0000,version=version)
 memory=c.create_string_buffer(b'\xff'*0x100000)
 c.memmove(c.addressof(memory)+0xb0000,recovery,len(recovery))
 allowed=c.create_string_buffer(hashlib.sha256(bytes(memory[:0xc000])).digest())
 authenticate=getattr(pairlib,'ota_pair_authenticate',None)
 assert callable(authenticate),'Legacy loader admission must use the same version-independent recovery contract'
 authenticate.argtypes=[c.c_void_p,c.c_size_t,c.c_void_p,c.c_size_t,c.c_void_p,c.POINTER(Info)]
 loader=(c.c_uint8*32)();out=Info()
 assert authenticate(memory,0x100000,allowed,1,loader,c.byref(out))==0
 assert bytes(out.output_digest)==hashlib.sha256(recovery).digest()
 assert bytes(loader)==allowed.raw[:32]
 # The existing installer API must still reject a different exact image.
 pairlib.ota_pair_verify.argtypes=[c.c_void_p,c.c_size_t,c.c_void_p,c.c_size_t,c.c_void_p,c.c_void_p,c.POINTER(Info)]
 assert pairlib.ota_pair_verify(memory,0x100000,allowed,1,hashlib.sha256(recovery).digest(),loader,c.byref(out))==0
 assert bytes(out.output_digest)==hashlib.sha256(recovery).digest() and bytes(loader)==allowed.raw[:32]
 assert pairlib.ota_pair_verify(memory,0x100000,allowed,1,bytes(out.signed_digest),loader,c.byref(out))<0
 assert bytes(loader)==bytes(32) and bytes(out)==bytes(c.sizeof(out))
 assert pairlib.ota_pair_verify(memory,0x100000,allowed,1,bytes(32),loader,c.byref(out))<0


@pytest.mark.parametrize('damage',['role','roleless','profile','signature','vectors','metadata_vectors','loader','capacity'])
def test_legacy_contract_rejects_unsupported_recovery_before_publishing_identity(pairlib,crypto,damage):
 recovery,_=image_fixture(crypto,role=None if damage=='roleless' else b'\x01' if damage=='role' else b'\x02',
  vector_base=0xc000 if damage=='vectors' else 0xb2808 if damage=='metadata_vectors' else 0xb0000,
  target=b'VIMAR30805\x01' if damage=='profile' else b'VIMAR30805\x02')
 if damage=='signature':recovery=recovery[:-1]+bytes([recovery[-1]^1])
 memory=c.create_string_buffer(b'\xff'*0x100000);c.memmove(c.addressof(memory)+0xb0000,recovery,len(recovery))
 allowed=c.create_string_buffer(bytes(32) if damage=='loader' else hashlib.sha256(bytes(memory[:0xc000])).digest())
 authenticate=getattr(pairlib,'ota_pair_authenticate',None)
 assert callable(authenticate)
 authenticate.argtypes=[c.c_void_p,c.c_size_t,c.c_void_p,c.c_size_t,c.c_void_p,c.POINTER(Info)]
 loader=(c.c_uint8*32)(*([0xa5]*32));out=Info();c.memset(c.byref(out),0xa5,c.sizeof(out))
 assert authenticate(memory,0xe0000 if damage=='capacity' else 0x100000,allowed,1,loader,c.byref(out))<0
 assert bytes(out)==bytes(c.sizeof(out)) and bytes(loader)==bytes(32)


def test_exact_operation_verification_never_falls_back_when_expected_hash_is_missing(pairlib,crypto):
 page,live,_,_=anchor_fixture();loader=CODE+page
 recovery,_=image_fixture(crypto,role=b'\x02',vector_base=0xb0000)
 allowed=records((2,hashlib.sha256(DOMAIN+CODE).digest()));out=Pair()
 c.memset(c.byref(out),0xa5,c.sizeof(out))
 assert pairlib.verify_pair(loader,len(loader),allowed,len(allowed),c.byref(live),recovery,len(recovery),None,c.byref(out))<0
 assert bytes(out)==bytes(c.sizeof(out))
 memory=c.create_string_buffer(b'\xff'*0x100000);c.memmove(c.addressof(memory)+0xb0000,recovery,len(recovery))
 hashes=c.create_string_buffer(hashlib.sha256(bytes(memory[:0xc000])).digest());actual=(c.c_uint8*32)();info=Info()
 pairlib.ota_pair_verify.argtypes=[c.c_void_p,c.c_size_t,c.c_void_p,c.c_size_t,c.c_void_p,c.c_void_p,c.POINTER(Info)]
 assert pairlib.ota_pair_verify(memory,0x100000,hashes,1,None,actual,c.byref(info))<0
