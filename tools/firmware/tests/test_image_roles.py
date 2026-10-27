"""Authenticated role contract: ephemeral keys, real crypto and SDK decoder.

The host-only source copy replaces the pinned public constants with a fresh
per-test-session public key; production files and private keys are never read.
"""
from local_inputs import local_input, sdk_root
import ctypes
import hashlib
import json
import lzma
from pathlib import Path
import re
import struct
import subprocess

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

ROOT = Path(__file__).resolve().parents[3]
SDK = sdk_root()
TARGET = b'VIMAR30805\x02'


class Info(ctypes.Structure):
    _fields_ = [('output_size', ctypes.c_uint32), ('image_version', ctypes.c_uint8 * 8),
               ('source_digest', ctypes.c_uint8 * 32), ('output_digest', ctypes.c_uint8 * 32),
               ('signed_digest', ctypes.c_uint8 * 32), ('authenticated_role', ctypes.c_uint8),
               ('authenticated_profile', ctypes.c_uint8)]


WRITE = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32,
                        ctypes.c_void_p, ctypes.c_size_t)


def tlv(tag, value):
    return struct.pack('<HH', tag, len(value)) + value


def area(magic, entries):
    return struct.pack('<HH', magic, 4 + len(entries)) + entries


@pytest.fixture(scope='module')
def crypto(tmp_path_factory):
    path = tmp_path_factory.mktemp('image_roles')
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.X962,
                                         serialization.PublicFormat.UncompressedPoint)
    der = key.public_key().public_bytes(serialization.Encoding.DER,
                                       serialization.PublicFormat.SubjectPublicKeyInfo)
    source = (ROOT / 'firmware/ota/ota_image.c').read_text()
    for name, value in [('public_key', public), ('public_key_hash', hashlib.sha256(der).digest())]:
        source, count = re.subn(r'(static const uint8_t ' + name + r'\[\d+\] = \{).*?\};',
            lambda m: m[1] + ','.join(hex(b) for b in value) + '};', source, count=1, flags=re.S)
        assert count == 1
    host = path / 'ota_image_test_key.c'
    host.write_text(source)
    nrf = local_input(SDK / 'nrf/subsys/nrf_compress')
    library = path / 'image_roles.so'
    subprocess.run(['cc', '-shared', '-fPIC', '-std=c11', '-O1',
        '-Wno-deprecated-declarations', '-DOTA_IMAGE_HOST', '-include',
        str(ROOT / 'tools/firmware/tests/ota_image_host/config.h'),
        '-I' + str(ROOT / 'firmware/ota'), '-I' + str(ROOT / 'firmware/recovery/src'),
        '-I' + str(ROOT / 'tools/firmware/tests/ota_image_host'),
        '-I' + str(SDK / 'nrf/include'), '-I' + str(nrf / 'lzma'), str(host),
        '-I'+str(ROOT/'firmware/src'), str(ROOT / 'firmware/recovery/src/recovery_primary.c'),
        str(ROOT / 'tools/firmware/tests/ota_image_host/registry.c'),
        *[str(nrf / p) for p in ['src/lzma.c', 'src/arm_thumb.c', 'lzma/LzmaDec.c',
                               'lzma/Lzma2Dec.c', 'lzma/armthumb.c']],
        '-lcrypto', '-o', str(library)], check=True, capture_output=True)
    dll = ctypes.CDLL(str(library))
    dll.ota_image_verify_primary_for_profile.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                                      ctypes.c_uint, ctypes.POINTER(Info)]
    dll.recovery_primary_validate.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    dll.ota_image_reconstruct_reader.argtypes = [ctypes.c_void_p, ctypes.c_uint32, WRITE,
                                                ctypes.c_void_p, ctypes.POINTER(Info)]
    return dll, key, hashlib.sha256(der).digest()


def fixture(crypto, role=b'\x01', *, target=TARGET, extra=b'', unprotected_extra=b'',
            ordinary_extra=None, version=(0, 5, 9, 0), vector_base=0xc000):
    _, key, keyhash = crypto
    payload = struct.pack('<II', 0x20010000, vector_base + 521) + bytes(range(256)) * 40
    entries = (tlv(0xa0, target) if target is not None else b'')
    if role is not None:
        entries += tlv(0xa1, role)
    entries += extra
    inner_entries = entries if ordinary_extra is None else ordinary_extra
    protected = area(0x6908, inner_entries) if inner_entries else b''
    header = struct.pack('<IIHHII', 0x96f3b83d, 0, 512, len(protected), len(payload), 0)
    header += struct.pack('<BBHI', *version) + bytes(484)
    signed = header + payload + protected

    def signing(data):
        digest = hashlib.sha256(data).digest()
        sig = key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        return digest, sig

    def unprotected(digest, signature):
        return area(0x6907, tlv(0x10, digest) + tlv(1, keyhash) + tlv(0x22, signature) + unprotected_extra)

    digest, sig = signing(signed)
    ordinary = signed + unprotected(digest, sig)
    stream = b'\x06\x5d' + lzma.compress(payload, format=lzma.FORMAT_RAW,
        filters=[{'id': lzma.FILTER_ARMTHUMB}, {'id': lzma.FILTER_LZMA2, 'dict_size': 32768,
                                               'lc': 3, 'lp': 0, 'pb': 2}])
    compressed_prot = area(0x6908, entries + tlv(0x70, struct.pack('<I', len(payload))) +
                           tlv(0x71, digest) + tlv(0x72, sig))
    compressed_header = bytearray(header)
    struct.pack_into('<HII', compressed_header, 10, len(compressed_prot), len(stream), 0xc00)
    compressed_signed = bytes(compressed_header) + stream + compressed_prot
    cdigest, csig = signing(compressed_signed)
    return ordinary, compressed_signed + unprotected(cdigest, csig)


def verify(crypto, ordinary, profile=2):
    info = Info()
    rc = crypto[0].ota_image_verify_primary_for_profile(ordinary, len(ordinary), profile, ctypes.byref(info))
    return rc, info


def reconstruct(crypto, compressed):
    class Reader(ctypes.Structure):
        _fields_ = [('size', ctypes.c_size_t), ('profile', ctypes.c_uint),
                    ('ctx', ctypes.c_void_p), ('read', WRITE)]
    @WRITE
    def read(ctx, offset, dest, n):
        ctypes.memmove(dest, compressed[offset:offset+n], n)
        return 0
    out = bytearray()
    @WRITE
    def write(ctx, offset, data, n):
        assert offset == len(out)
        out.extend(ctypes.string_at(data, n))
        return 0
    reader, info = Reader(len(compressed), 2, None, read), Info()
    rc = crypto[0].ota_image_reconstruct_reader(ctypes.byref(reader), 0xa2000, write, None, ctypes.byref(info))
    return rc, out, info


@pytest.mark.parametrize('role', range(1, 6))
def test_roles_are_authenticated_and_survive_sdk_reconstruction(crypto, role):
    ordinary, compressed = fixture(crypto, bytes([role]))
    rc, info = verify(crypto, ordinary)
    assert rc == 0
    assert (info.authenticated_role, info.authenticated_profile) == (role, 2)
    rc, out, info = reconstruct(crypto, compressed)
    assert rc == 0 and out == ordinary
    assert (info.authenticated_role, info.authenticated_profile) == (role, 2)
    assert crypto[0].recovery_primary_validate(ordinary, len(ordinary)) == (0 if role == 1 else -13)


@pytest.mark.parametrize('role', [None, b'\x02', b'\x03', b'\x04', b'\x05'])
def test_same_profile_without_main_role_is_never_exit_authorization(crypto, role):
    ordinary, _ = fixture(crypto, role)
    assert verify(crypto, ordinary)[0] == 0
    assert crypto[0].recovery_primary_validate(ordinary, len(ordinary)) != 0


@pytest.mark.parametrize('options', [
    {'role': b''}, {'role': b'\x00'}, {'role': b'\x06'}, {'role': b'\xff'},
    {'role': b'\x01\x00'}, {'extra': tlv(0xa1, b'\x01')},
    {'unprotected_extra': tlv(0xa1, b'\x01')}, {'target': None},
    {'extra': tlv(0xa2, b'\x01')},
])
def test_invalid_duplicate_unprotected_unbound_and_unknown_roles_reject_before_write(crypto, options):
    ordinary, compressed = fixture(crypto, **options)
    rc, info = verify(crypto, ordinary)
    assert rc < 0
    assert info.authenticated_role == info.authenticated_profile == 0
    rc, out, _ = reconstruct(crypto, compressed)
    assert rc < 0 and out == b''


def test_wrong_profile_or_invalid_signature_cannot_expose_role(crypto):
    ordinary, _ = fixture(crypto)
    rc, info = verify(crypto, ordinary, profile=1)
    assert rc < 0 and info.authenticated_role == info.authenticated_profile == 0
    damaged = bytearray(ordinary)
    damaged[600] ^= 1
    rc, info = verify(crypto, bytes(damaged))
    assert rc < 0 and info.authenticated_role == info.authenticated_profile == 0
    assert crypto[0].recovery_primary_validate(bytes(damaged), len(damaged)) < 0


def test_main_role_requires_current_split_profile_for_exit(crypto):
    ordinary, _ = fixture(crypto, target=b'VIMAR30805\x01')
    assert verify(crypto, ordinary, profile=1)[0] == 0
    assert crypto[0].recovery_primary_validate(ordinary, len(ordinary)) < 0


def test_compressed_role_cannot_change_inner_authenticated_role(crypto):
    ordinary_entries = tlv(0xa0, TARGET) + tlv(0xa1, b'\x03')
    _, compressed = fixture(crypto, ordinary_extra=ordinary_entries)
    rc, out, _ = reconstruct(crypto, compressed)
    assert rc < 0 and out == b''


@pytest.fixture
def package_sources(crypto, tmp_path, monkeypatch):
    from tools.firmware import package_zigbee_ota as pkg
    local_input(pkg.IMGTOOL)
    local_input(pkg.PYTHON)
    _, key, _ = crypto
    private = tmp_path / 'ephemeral-private.pem'
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public = tmp_path / 'ephemeral-public.pem'
    public.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo))
    monkeypatch.setattr(pkg, 'PRIVATE_KEY', private)
    monkeypatch.setattr(pkg, 'PUBLIC_KEY', public)

    def manifest(role=None, *, candidate_role=None, profile=1):
        def record(name, data):
            path = tmp_path / name
            path.write_bytes(data)
            return dict(path=str(path), sha256=hashlib.sha256(data).hexdigest())
        target = b'VIMAR30805' + bytes([profile])
        current, _ = fixture(crypto, role=None, target=target, version=(0, 5, 8, 0))
        candidate, _ = fixture(crypto, role=candidate_role, target=target)
        parsed = pkg.image(candidate)
        unsigned = bytes(512) + candidate[512:512+parsed['size']]
        data = dict(schema_version=1, version='0.5.9', manufacturer_code=0xfff1,
                    image_type=0x3085, hardware_min=1, hardware_max=1,
                    current_signed=record('current.bin', current),
                    candidate_signed=record('candidate.bin', candidate),
                    candidate_unsigned=record('candidate.raw', unsigned))
        if profile == 2:
            recovery, _ = fixture(crypto, role=b'\x02', target=target, vector_base=0xb0000)
            data.update(ota_profile=2, minimum_source_version='0.5.7+1',
                        recovery_signed=record('recovery.bin', recovery),
                        pair_bindings=record('bindings.json', json.dumps(dict(
                            schema_version=1, ota_profile=2, recovery_sha256=hashlib.sha256(recovery).hexdigest(),
                            allowed_loaders=['11'*32])).encode()))
        if role is not None:
            data['image_role'] = role
        path = tmp_path / 'manifest.json'
        path.write_text(json.dumps(data))
        return path
    return pkg, manifest


@pytest.mark.parametrize('name,value', [('main', 1), ('recovery', 2), ('migration', 3),
                                        ('restore', 4), ('diagnostic', 5)])
@pytest.mark.parametrize('inherited', [False, True])
def test_packager_explicit_or_preserved_role_is_signed_in_both_images(package_sources,
                                                                    tmp_path, name, value, inherited):
    pkg, manifest = package_sources
    path = manifest(None if inherited else name, candidate_role=bytes([value]) if inherited else None)
    result = pkg.package_release(path, tmp_path / 'release')
    for field in ('compressed_path', 'reconstructed_path'):
        parsed = pkg.image(Path(result[field]).read_bytes())
        assert parsed['protected'][0xa1] == bytes([value])
        assert 0xa1 not in parsed['unprotected']
    report = json.loads(Path(result['report_path']).read_text())
    assert report['image_role'] == name and report['image_role_tlv'] == 0xa1


def test_packager_never_infers_main_from_model_profile(package_sources, tmp_path):
    pkg, manifest = package_sources
    result = pkg.package_release(manifest(), tmp_path / 'release')
    for field in ('compressed_path', 'reconstructed_path'):
        assert 0xa1 not in pkg.image(Path(result[field]).read_bytes())['protected']
    assert json.loads(Path(result['report_path']).read_text())['image_role'] is None


def test_packager_cannot_relabel_authenticated_helper_as_main(package_sources, tmp_path):
    pkg, manifest = package_sources
    with pytest.raises(ValueError, match='role'):
        pkg.package_release(manifest('main', candidate_role=b'\x03'), tmp_path / 'release')
    assert not (tmp_path / 'release').exists()


@pytest.mark.parametrize('role', ['none', 'MAIN', 'invalid', 1, True])
def test_packager_requires_explicit_supported_role_name(package_sources, tmp_path, role):
    pkg, manifest = package_sources
    with pytest.raises(ValueError, match='role'):
        pkg.package_release(manifest(role), tmp_path / 'release')
    assert not (tmp_path / 'release').exists()


def test_packager_rejects_external_signer_dropping_requested_role(package_sources, tmp_path, monkeypatch):
    pkg, manifest = package_sources
    original = pkg.run_imgtool
    def drop_role(arguments, commands):
        args = list(arguments)
        if args[0] == 'sign':
            for i in range(len(args) - 2):
                if args[i] == '--custom-tlv-file' and args[i+1] == '0xa1':
                    del args[i:i+3]
                    break
        return original(args, commands)
    monkeypatch.setattr(pkg, 'run_imgtool', drop_role)
    with pytest.raises(ValueError, match='role'):
        pkg.package_release(manifest('main'), tmp_path / 'release')
    assert not (tmp_path / 'release').exists()


@pytest.mark.parametrize('role,candidate_role,expected', [(None, None, None), ('migration', None, b'\x03'),
                                                       (None, b'\x03', b'\x03'), ('main', None, b'\x01')])
def test_split_profile_does_not_imply_main_role(package_sources, tmp_path, role, candidate_role, expected):
    pkg, manifest = package_sources
    result = pkg.package_release(manifest(role, candidate_role=candidate_role, profile=2), tmp_path / 'release')
    for field in ('compressed_path', 'reconstructed_path'):
        metadata = pkg.image(Path(result[field]).read_bytes())['protected']
        assert metadata[0xa0] == b'VIMAR30805\x02'
        assert metadata.get(0xa1) == expected
