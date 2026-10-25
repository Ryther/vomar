"""Actual SDK nrf_compress decoder + cryptographic signed fixture tests."""
from local_inputs import local_input, sdk_root
import ctypes
import hashlib
import lzma
import struct
import sys
import subprocess
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

ROOT = Path(__file__).resolve().parents[3]
SDK = sdk_root()

class Info(ctypes.Structure):
    _fields_ = [('output_size', ctypes.c_uint32), ('image_version', ctypes.c_uint8 * 8),
                ('source_digest', ctypes.c_uint8 * 32), ('output_digest', ctypes.c_uint8 * 32),
                ('signed_digest', ctypes.c_uint8 * 32),
                ('authenticated_role', ctypes.c_uint8), ('authenticated_profile', ctypes.c_uint8)]

WRITE = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_size_t)

def tlv(t, b):
    return struct.pack('<HH', t, len(b)) + b

def fixture(payload=None, *, stream=None, decomp_size=None, protected_extra=b'', wrong_key=False, bad_decomp_sig=False, counter=None, target=b'VIMAR30805\x01', version=(0,6,1,4)):
    if payload is None:
        payload = (bytes.fromhex('00f001f8') * 20000) + bytes(range(256)) * 100
    key = serialization.load_pem_private_key(local_input(ROOT / 'firmware/keys/dev-private.pem').read_bytes(), None)
    pinned = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    if wrong_key:
        key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    version = struct.pack('<BBHI', *version)
    entries = b'' if target is None else tlv(0xa0, target)
    if counter is not None:
        entries += tlv(0x50, struct.pack('<I', counter))
    ordinary_prot = struct.pack('<HH', 0x6908, 4+len(entries))+entries if entries else b''
    h = struct.pack('<IIHHII', 0x96f3b83d, 0, 512, len(ordinary_prot), len(payload), 0) + version + bytes(4)
    ordinary_h = h + bytes(512 - 32)
    digest = hashlib.sha256(ordinary_h + payload + ordinary_prot).digest()
    sig = key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    if bad_decomp_sig:
        sig = sig[:-1] + bytes([sig[-1] ^ 1])
    if stream is None:
        stream = bytes([6, 93]) + lzma.compress(payload, format=lzma.FORMAT_RAW,
          filters=[{'id': lzma.FILTER_ARMTHUMB}, {'id': lzma.FILTER_LZMA2, 'dict_size': 32768, 'lc': 3, 'lp': 0, 'pb': 2}])
    prot = ordinary_prot[4:] + tlv(0x70, struct.pack('<I', len(payload) if decomp_size is None else decomp_size)) + tlv(0x71, digest) + tlv(0x72, sig) + protected_extra
    prot = struct.pack('<HH', 0x6908, 4 + len(prot)) + prot
    compressed_h = bytearray(ordinary_h)
    struct.pack_into('<HII', compressed_h, 10, len(prot), len(stream), 0xc00)
    signed = compressed_h + stream + prot
    cdigest = hashlib.sha256(signed).digest()
    csig = key.sign(cdigest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    def unprotected(d, s):
        entries = tlv(0x10, d) + tlv(1, hashlib.sha256(pinned).digest()) + tlv(0x22, s)
        return struct.pack('<HH', 0x6907, 4 + len(entries)) + entries
    return bytes(signed + unprotected(cdigest, csig)), ordinary_h + payload + ordinary_prot + unprotected(digest, sig)

def build_test_library(tmp_path_factory,split=False):
    target = tmp_path_factory.mktemp('ota_image') / 'libimage.so'
    nrf = local_input(SDK / 'nrf/subsys/nrf_compress')
    cmd = ['cc', *(['-DCONFIG_VIMAR_OTA_SPLIT_STAGING=1'] if split else []), '-shared', '-fPIC', '-std=c11', '-O1', '-DOTA_IMAGE_HOST', '-DOTA_INSTALL_HOST', '-include',
           str(ROOT / 'tools/firmware/tests/ota_image_host/config.h'),
           '-I' + str(ROOT / 'firmware/ota'), '-I' + str(ROOT / 'tools/firmware/tests/ota_image_host'),
           '-I' + str(SDK / 'nrf/include'), '-I' + str(nrf / 'lzma'),
           str(ROOT / 'firmware/ota/ota_image.c'),
           str(ROOT/'firmware/ota/ota_split_stage.c'),str(ROOT/'firmware/ota/ota_pair.c'),
           str(ROOT / 'firmware/recovery/src/ota_install.c'),
           str(ROOT / 'firmware/ota/ota_transaction.c'),
           str(ROOT / 'firmware/ota/ota_format.c'),
           str(ROOT / 'tools/firmware/tests/ota_image_host/registry.c'),
           str(ROOT / 'tools/firmware/tests/ota_image_host/primary_verify_wrap.c'),
           '-Wl,--wrap=ota_image_verify_primary',
           *[str(nrf / p) for p in ['src/lzma.c', 'src/arm_thumb.c', 'lzma/LzmaDec.c', 'lzma/Lzma2Dec.c', 'lzma/armthumb.c']],
           '-lcrypto', '-o', str(target)]
    subprocess.run(cmd, check=True)
    so = ctypes.CDLL(str(target))
    so.ota_image_validate.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.POINTER(Info)]
    so.ota_image_reconstruct.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, WRITE, ctypes.c_void_p, ctypes.POINTER(Info)]
    return so

@pytest.fixture(scope='session')
def lib(tmp_path_factory):
    return build_test_library(tmp_path_factory)

def run(lib, source, limit=0xa2000, fail_at=None):
    output = bytearray()
    calls = []
    @WRITE
    def write(ctx, offset, data, size):
        calls.append(offset)
        if fail_at is not None and offset + size > fail_at:
            return -5
        assert offset == len(output)
        output.extend(ctypes.string_at(data, size))
        return 0
    info = Info()
    result = lib.ota_image_reconstruct(source, len(source), limit, write, None, ctypes.byref(info))
    return result, output, calls, info

def test_signed_sdk_roundtrip(lib):
    source, expected = fixture()
    rc, output, calls, info = run(lib, source)
    assert rc == 0
    assert output == expected
    assert bytes(info.output_digest) == hashlib.sha256(output).digest()
    assert bytes(info.source_digest) == hashlib.sha256(source).digest()
    assert info.output_size == len(expected)

@pytest.mark.parametrize('kind', ['signature', 'payload', 'truncated', 'dictionary', 'trailing_stream', 'output_overrun', 'duplicate', 'trailing_file', 'limit'])
def test_reject_before_first_write(lib, kind):
    source, expected = fixture()
    limit = 0xa2000
    if kind == 'signature': source = source[:-1] + bytes([source[-1] ^ 1])
    if kind == 'payload': source = source[:520] + bytes([source[520] ^ 1]) + source[521:]
    if kind == 'truncated': source = source[:-20]
    if kind == 'trailing_file': source += b'\0'
    if kind == 'dictionary': source, _ = fixture(stream=b'\x07\x5d\0')
    if kind == 'trailing_stream': source, _ = fixture(stream=b'\x06\x5d\0\0')
    if kind == 'output_overrun': source, _ = fixture(decomp_size=16)
    if kind == 'duplicate': source, _ = fixture(protected_extra=tlv(0x70, struct.pack('<I', 16)))
    if kind == 'limit': limit = len(expected) - 1
    rc, _, calls, _ = run(lib, source, limit)
    assert rc < 0
    assert calls == []

def test_write_failure_propagates_and_restart(lib):
    source, expected = fixture()
    for boundary in range(4096, len(expected), 4096):
        rc, _, _, _ = run(lib, source, fail_at=boundary)
        assert rc == -5
    assert run(lib, source)[1] == expected

def test_real_imgtool_artifact(lib,tmp_path):
    legacy = local_input(ROOT / 'experiments/vimar-zigbee-integration-20261020/feasibility-only-NOT-FLASH-lzma2armthumb.bin').read_bytes()
    # The historical feasibility artifact lacks authenticated target identity and
    # must now be rejected. Re-sign its real application payload with SDK imgtool.
    assert run(lib,legacy)[0]<0
    compressed_size=struct.unpack_from('<I',legacy,12)[0]
    payload=lzma.decompress(legacy[514:512+compressed_size],format=lzma.FORMAT_RAW,
        filters=[{'id':lzma.FILTER_ARMTHUMB},{'id':lzma.FILTER_LZMA2,'dict_size':32768}])
    raw=tmp_path/'application.bin'; raw.write_bytes(bytes(512)+payload)
    target=tmp_path/'target.bin'; target.write_bytes(b'VIMAR30805\x01')
    compressed=tmp_path/'compressed.bin'
    tool=str(SDK/'bootloader/mcuboot/scripts/imgtool.py')
    subprocess.run([sys.executable,tool,'sign','-k',str(ROOT/'firmware/keys/dev-private.pem'),
        '--header-size','512','--slot-size','0xa4000','--align','4','--version','0.6.1+4',
        '--compression','lzma2armthumb','--compression-lzma-dictsize','32768',
        '--compression-lzma-lp','0','--custom-tlv-file','0xa0',str(target),str(raw),str(compressed)],check=True)
    rc,output,_,info=run(lib,compressed.read_bytes())
    assert rc==0 and info.output_size>380000
    path=tmp_path/'reconstructed.bin'; path.write_bytes(output)
    subprocess.run([sys.executable,tool,'verify','-k',str(ROOT/'firmware/keys/dev-public.pem'),str(path)],check=True)

@pytest.mark.parametrize('kind', ['wrong_key', 'bad_decomp_sig', 'truncated_stream', 'lc_lp_overflow', 'corrupt_resigned', 'signed_digest_mismatch', 'unknown_protected'])
def test_malicious_but_signed_metadata(lib, kind):
    if kind == 'wrong_key':
        source, _ = fixture(wrong_key=True)
    elif kind == 'bad_decomp_sig':
        source, _ = fixture(bad_decomp_sig=True)
    elif kind == 'unknown_protected':
        source, _ = fixture(protected_extra=tlv(0x73, b'1234'))
    else:
        base, _ = fixture()
        length = struct.unpack_from('<I', base, 12)[0]
        stream = bytearray(base[512:512+length])
        if kind == 'truncated_stream': stream = stream[:-1]
        if kind == 'lc_lp_overflow': stream[7] = 94 # first chunk property lc=4
        if kind == 'corrupt_resigned': stream[len(stream)//2] ^= 0x88
        if kind == 'signed_digest_mismatch':
            # Same length and valid stream but signed expected digest is different.
            source, _ = fixture(payload=b'Z' * 105600, stream=bytes(stream))
        else:
            source, _ = fixture(stream=bytes(stream))
    result, _, writes, _ = run(lib, source)
    assert result < 0
    assert writes == []

@pytest.mark.parametrize('payload', [b'X', b'\0' * 32768, b'\x00\xf0' * 16385, bytes(range(256))*129])
def test_decoder_chunk_boundaries(lib, payload):
    source, expected = fixture(payload=payload)
    rc, actual, _, _ = run(lib, source)
    assert rc == 0
    assert actual == expected

def test_protected_security_counter_is_preserved(lib):
    source, expected = fixture(counter=17)
    rc, actual, _, _ = run(lib, source)
    assert rc == 0
    assert actual == expected

@pytest.mark.parametrize('target', [None, b'VIMAR30804\x01', b'VIMAR30805\x02', b'VIMAR30805', b'VIMAR30805\x01\0'])
def test_authenticated_wrong_or_missing_target_rejected(lib,target):
    source,_=fixture(target=target)
    rc,_,writes,_=run(lib,source)
    assert rc<0 and writes==[]

def test_duplicate_protected_target_rejected(lib):
    source,_=fixture(protected_extra=tlv(0xa0,b'VIMAR30805\x01'))
    rc,_,writes,_=run(lib,source)
    assert rc<0 and writes==[]

@pytest.mark.parametrize('target',[None,b'VIMAR30805\x01'])
def test_primary_signature_verification_supports_legacy(lib,target):
    _,ordinary=fixture(target=target)
    verify=lib.ota_image_verify_primary
    verify.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(Info)]
    info=Info()
    assert verify(ordinary,len(ordinary),ctypes.byref(info))==0
    assert info.output_size==len(ordinary)
    corrupt=ordinary[:600]+bytes([ordinary[600]^1])+ordinary[601:]
    assert verify(corrupt,len(corrupt),ctypes.byref(info))<0

class Reader(ctypes.Structure):
    _fields_=[('size',ctypes.c_size_t),('profile',ctypes.c_uint),('ctx',ctypes.c_void_p),('read',WRITE)]

def fragmented(source, split, profile=2, fail_at=None):
    # Two unrelated backing allocations; a direct source pointer cannot work.
    left,right=source[:split],source[split:]
    @WRITE
    def read(ctx,offset,dest,n):
        if fail_at is not None and offset<=fail_at<offset+n:
            return -5
        if offset+n>len(source):
            return -22
        if offset<split:
            a=left[offset:min(offset+n,split)]
            value=a+right[:n-len(a)]
        else:
            value=right[offset-split:offset-split+n]
        ctypes.memmove(dest,value,n)
        return 0
    return Reader(len(source),profile,None,read),read

def run_reader(lib,source,split,profile=2,fail_at=None):
    reader,callback=fragmented(source,split,profile,fail_at)
    output=bytearray()
    @WRITE
    def write(ctx,offset,data,n):
        assert offset==len(output)
        output.extend(ctypes.string_at(data,n));return 0
    fn=lib.ota_image_reconstruct_reader
    fn.argtypes=[ctypes.POINTER(Reader),ctypes.c_uint32,WRITE,ctypes.c_void_p,ctypes.POINTER(Info)]
    info=Info();rc=fn(ctypes.byref(reader),0xa2000,write,None,ctypes.byref(info))
    return rc,bytes(output),info

@pytest.mark.parametrize('profile',[1,2])
def test_real_decoder_across_fragmented_header_stream_tlv_signature(lib,profile):
    source,expected=fixture(target=b'VIMAR30805'+bytes([profile]),counter=7)
    protected=512+int.from_bytes(source[12:16],'little')
    cuts=sorted({1,7,10,12,20,31,32,511,512,513,600,767,768,1023,
                 *range(protected,len(source))})
    for cut in cuts:
        if cut>=len(source):continue
        rc,out,info=run_reader(lib,source,cut,profile)
        assert rc==0,(cut,rc)
        assert out==expected
        assert bytes(info.source_digest)==hashlib.sha256(source).digest()
        assert bytes(info.output_digest)==hashlib.sha256(expected).digest()

@pytest.mark.parametrize('target,profile',[(b'VIMAR30805\x01',2),(b'VIMAR30805\x02',1)])
def test_fragmented_profile_mismatch_never_writes(lib,target,profile):
    source,_=fixture(target=target)
    rc,out,_=run_reader(lib,source,513,profile)
    assert rc!=0 and out==b''

def test_fragmented_io_or_signature_failure_never_writes(lib):
    source,_=fixture(target=b'VIMAR30805\x02')
    for fail_at in [0,511,512,600,len(source)-1]:
        rc,out,_=run_reader(lib,source,513,fail_at=fail_at)
        assert rc!=0 and out==b''
    broken=bytearray(source);broken[-1]^=1
    rc,out,_=run_reader(lib,bytes(broken),513)
    assert rc!=0 and out==b''
