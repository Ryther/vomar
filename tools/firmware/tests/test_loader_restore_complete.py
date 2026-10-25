"""Independent 1 MiB original image, SHA256 page table, and real OpenSSL host IO."""
import ctypes as c
import hashlib
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / 'firmware/loader_contract'
SIZE, BOOT, PAGE = 0x100000, 0xc000, 4096

class Anchor(c.Structure):
    _fields_ = [('variant', c.c_uint32), ('uid', c.c_uint32 * 2),
                ('flash_sha256', c.c_uint8 * 32), ('uicr_sha256', c.c_uint8 * 32),
                ('table_sha256', c.c_uint8 * 32)]

class Session(c.Structure):
    _fields_ = [('anchor', Anchor), ('table', c.c_uint8 * 8192),
                ('initialized', c.c_bool), ('accepted', c.c_bool), ('writing', c.c_bool)]

@pytest.fixture(scope='module')
def lib(tmp_path_factory):
    path = tmp_path_factory.mktemp('restore_complete') / 'complete.so'
    sources = [CORE / 'loader_contract.c', Path(__file__).with_name('loader_restore_complete_host.c')]
    if (CORE / 'loader_restore_complete.c').exists():
        sources += [CORE / 'loader_restore_complete.c']
    subprocess.run(['cc', '-shared', '-fPIC', '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror',
                    *(['-fsanitize=undefined', '-fno-sanitize-recover=all'] if os.environ.get('LOADER_COMPLETE_UBSAN') else []),
                    '-Werror=vla', '-I' + str(CORE), *map(str, sources), '-lcrypto', '-o', str(path)],
                   check=True, capture_output=True)
    lib = c.CDLL(str(path))
    lib.complete_prepare.argtypes = [c.POINTER(Session), c.POINTER(Anchor), c.c_void_p]
    lib.complete_verify.argtypes = [c.POINTER(Session), c.c_void_p, c.c_size_t, c.c_uint32,
                                    c.c_void_p, c.c_size_t, c.c_uint]
    lib.complete_inject.argtypes = [c.c_uint, c.c_int, c.c_uint32, c.c_int]
    lib.loader_restore_session_reset.argtypes = [c.POINTER(Session)]
    return lib

@pytest.fixture
def image(lib):
    original = bytearray(bytes((i * 37 + (i >> 12) * 13) & 255 for i in range(SIZE)))
    original[0xb0000:0xef000] = b'\xff' * 0x3f000
    original = bytes(original)
    table = b''.join(hashlib.sha256(original[i:i + PAGE]).digest() for i in range(0, SIZE, PAGE))
    a = Anchor(0x41414430, (c.c_uint32 * 2)(0x11223344, 0x55667788),
               (c.c_uint8 * 32).from_buffer_copy(hashlib.sha256(original).digest()),
               (c.c_uint8 * 32).from_buffer_copy(hashlib.sha256(b'local UICR').digest()),
               (c.c_uint8 * 32).from_buffer_copy(hashlib.sha256(table).digest()))
    s = Session()
    lib.complete_inject(0, 0, 0, 0)
    assert lib.complete_prepare(c.byref(s), c.byref(a), table) == 0
    actual = bytearray(original)
    actual[:BOOT] = b'\x71' * BOOT  # Currently installed custom loader and anchor.
    actual[0xb0000:0xef000] = b'\x93' * 0x3f000  # Running RESTORE image: never assume erased.
    lib.complete_inject(0, 0, 0, 0)
    return s, original[:BOOT], bytes(actual), original

def verify(lib, image, **kw):
    s, boot, flash, _ = image
    return lib.complete_verify(c.byref(s) if s is not None else None, kw.get('boot', boot),
                               kw.get('size', len(boot)), kw.get('mask', 0xfff),
                               kw.get('flash', flash), kw.get('flash_size', len(flash)), kw.get('missing', 0))

def test_virtual_original_matches_despite_actual_custom_boot_and_live_restorer(lib, image):
    before = bytes(image[0])
    assert hashlib.sha256(image[2]).digest() != bytes(image[0].anchor.flash_sha256)
    assert verify(lib, image) == 0
    assert bytes(image[0]) == before
    assert lib.complete_reads() > 0 and lib.complete_forbidden() == 0

@pytest.mark.parametrize('mask', [0, 1, 0x1fff, 0xffffffff] + [0xfff ^ (1 << i) for i in range(12)])
def test_every_boot_page_and_no_unknown_mask_bits_required(lib, image, mask):
    assert verify(lib, image, mask=mask) < 0
    assert lib.complete_reads() == 0

@pytest.mark.parametrize('size', [0, BOOT - 1, BOOT + 1])
def test_boot_staging_size_is_exact(lib, image, size):
    assert verify(lib, image, size=size) < 0

@pytest.mark.parametrize('field', ['initialized', 'accepted', 'writing'])
def test_missing_session_state_fails_closed(lib, image, field):
    setattr(image[0], field, False)
    assert verify(lib, image) < 0

def test_reset_session_is_not_authorized(lib, image):
    lib.loader_restore_session_reset(c.byref(image[0]))
    assert verify(lib, image) < 0

@pytest.mark.parametrize('address', [0, BOOT - 1, 0xc000, 0xaffff, 0xef000, 0xfffff])
def test_changed_logical_page_is_rejected(lib, image, address):
    if address < BOOT:
        data = bytearray(image[1]); data[address] ^= 1
        assert verify(lib, image, boot=bytes(data)) < 0
    else:
        data = bytearray(image[2]); data[address] ^= 1
        assert verify(lib, image, flash=bytes(data)) < 0

@pytest.mark.parametrize('field', ['table', 'flash_sha256', 'table_sha256'])
def test_corrupted_trusted_metadata_cannot_pass(lib, image, field):
    data = image[0].table if field == 'table' else getattr(image[0].anchor, field)
    data[0] ^= 1
    assert verify(lib, image) < 0

def test_table_with_non_erased_original_scratch_is_rejected_even_if_its_digest_matches(lib, image):
    s = image[0]
    start = (0xb0000 // PAGE) * 32
    s.table[start] ^= 1
    digest = hashlib.sha256(bytes(s.table)).digest()
    s.anchor.table_sha256[:] = digest
    assert verify(lib, image) < 0

@pytest.mark.parametrize('address', [0xc000, 0xef000, 0xfffff])
def test_change_after_page_checks_is_detected_by_full_logical_digest(lib, image, address):
    # An intentionally nonimmutable test reader changes only its second pass.
    # A verifier that merely checks page hashes would incorrectly accept it.
    lib.complete_mutate_second(address)
    assert verify(lib, image) < 0

@pytest.mark.parametrize('size', [0, SIZE - 1, SIZE + 1])
def test_actual_reader_geometry_is_exact(lib, image, size):
    assert verify(lib, image, flash_size=size) < 0
    assert lib.complete_reads() == 0

@pytest.mark.parametrize('missing', range(1, 6))
def test_incomplete_callbacks_rejected_without_begin(lib, image, missing):
    assert verify(lib, image, missing=missing) < 0
    assert lib.complete_steps() == 0

@pytest.mark.parametrize('address', [0xc000, 0xaffff, 0xef000, 0xfffff])
@pytest.mark.parametrize('rc', [-5, 1])
def test_bounded_flash_read_failures_reject(lib, image, address, rc):
    lib.complete_inject(0, 0, address, rc)
    assert verify(lib, image) == -5
    assert lib.complete_forbidden() == 0

def test_null_inputs_reject(lib, image):
    assert verify(lib, (None, *image[1:])) < 0
    assert verify(lib, image, boot=None) < 0

def test_callback_cancellation_is_propagated_and_releases_crypto(lib, image):
    lib.complete_inject(1, -125, 0, 0)
    assert verify(lib, image) == -125
    assert lib.complete_aborts() == lib.complete_begins() == 1
    lib.complete_inject(0, 0, 0xef000, -125)
    assert verify(lib, image) == -125
    assert lib.complete_aborts() == lib.complete_begins()

def test_all_crypto_boundaries_fail_closed_and_release_context(lib, image):
    assert verify(lib, image) == 0
    steps = lib.complete_steps()
    # All begin/update/finish calls for the table, erased page, 193 logical
    # nonscratch pages, and full stream. Each failed begin also needs abort.
    for step in range(1, steps + 1):
        lib.complete_inject(step, -5, 0, 0)
        assert verify(lib, image) == -5, step
        assert lib.complete_aborts() == lib.complete_begins() >= 1, step
    for step in [1, 2, steps]:
        lib.complete_inject(step, 1, 0, 0)
        assert verify(lib, image) == -5
        assert lib.complete_aborts() == lib.complete_begins()
