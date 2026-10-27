"""Explicit migration boot authorization; real ephemeral-key ECDSA fixtures."""
from local_inputs import local_input, sdk_root
import ctypes
import hashlib
import struct
from pathlib import Path
import subprocess

import pytest

from test_image_roles import crypto, fixture

ROOT = Path(__file__).resolve().parents[3]


def test_migration_and_sdk_reset_transition_ownership(tmp_path):
    exe = tmp_path / 'migration_control'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=undefined',
        '-I' + str(ROOT / 'firmware/recovery/src'),
        str(ROOT / 'firmware/recovery/src/recovery_exit_control.c'),
        str(Path(__file__).with_name('recovery_migration_control_test.c')), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


def signed_hash(blob):
    end = 512 + struct.unpack_from('<I', blob, 12)[0] + struct.unpack_from('<H', blob, 10)[0]
    return hashlib.sha256(blob[:end]).digest()


def migration(crypto, blob, expected=None, size=None):
    fn = getattr(crypto[0], 'recovery_primary_validate_migration', None)
    assert fn is not None, 'Explicit hash-pinned MIGRATION authorization is missing'
    fn.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
    return fn(blob, len(blob) if size is None else size, expected)


def uploaded(crypto, blob):
    fn = getattr(crypto[0], 'recovery_primary_validate_upload', None)
    assert fn is not None, 'Completed-upload authorization must be separate from MAIN exit'
    fn.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    return fn(blob, len(blob))


def test_exact_signed_migration_is_explicitly_bootable_but_never_normal_exit(crypto):
    blob, _ = fixture(crypto, role=b'\x03')
    assert migration(crypto, blob, signed_hash(blob)) == 0
    assert uploaded(crypto, blob) == 0
    assert crypto[0].recovery_primary_validate(blob, len(blob)) < 0


@pytest.mark.parametrize('role', [None, b'\x01', b'\x02', b'\x04', b'\x05'])
def test_every_other_signed_role_rejects_explicit_migration(crypto, role):
    blob, _ = fixture(crypto, role=role)
    assert migration(crypto, blob, signed_hash(blob)) < 0


@pytest.mark.parametrize('target', [None, b'VIMAR30805\x01', b'OTHER30805\x02'])
def test_migration_needs_protected_exact_project_profile2(crypto, target):
    blob, _ = fixture(crypto, role=b'\x03', target=target)
    assert migration(crypto, blob, signed_hash(blob)) < 0
    assert uploaded(crypto, blob) < 0


def test_expected_signed_hash_is_required_and_full_file_hash_is_not_a_substitute(crypto):
    blob, _ = fixture(crypto, role=b'\x03')
    assert migration(crypto, blob, None) < 0
    assert migration(crypto, blob, b'\0' * 32) < 0
    assert migration(crypto, blob, hashlib.sha256(blob).digest()) < 0


def test_signature_payload_and_extent_are_verified_before_migration_authority(crypto):
    blob, compressed = fixture(crypto, role=b'\x03')
    for damaged in [blob[:-1], bytes([blob[0] ^ 1]) + blob[1:],
                    blob[:600] + bytes([blob[600] ^ 1]) + blob[601:],
                    blob[:-1] + bytes([blob[-1] ^ 1]), compressed]:
        assert migration(crypto, damaged, signed_hash(blob)) < 0
    assert migration(crypto, blob, signed_hash(blob), len(blob) - 1) < 0
    assert migration(crypto, blob + b'\xff' * 20, signed_hash(blob)) == 0


@pytest.mark.parametrize('base', [0, 0xb0000, 0xa6000])
def test_authenticated_helper_linked_outside_primary_payload_is_rejected(crypto, base):
    blob, _ = fixture(crypto, role=b'\x03', vector_base=base)
    assert migration(crypto, blob, signed_hash(blob)) < 0


@pytest.mark.parametrize('role', [b'\x02', b'\x04', b'\x05', None])
def test_upload_completion_cannot_clear_partial_intent_for_other_roles(crypto, role):
    blob, _ = fixture(crypto, role=role)
    assert uploaded(crypto, blob) < 0


def test_signed_main_upload_completion_does_not_grant_helper_authority(crypto):
    blob, _ = fixture(crypto, role=b'\x01')
    assert uploaded(crypto, blob) == 0
    assert crypto[0].recovery_primary_validate(blob, len(blob)) == 0
    assert migration(crypto, blob, signed_hash(blob)) < 0


def test_actual_project_pinned_key_accepts_only_exact_common_candidate_migration(tmp_path):
    library = tmp_path / 'actual.so'
    subprocess.run(['cc', '-shared', '-fPIC', '-std=c11', '-Wno-deprecated-declarations',
        '-DOTA_IMAGE_AUTH_ONLY', '-DOTA_IMAGE_HOST', '-I' + str(ROOT / 'firmware/recovery/src'),
        '-I' + str(ROOT / 'firmware/src'), '-I' + str(ROOT / 'firmware/ota'), str(ROOT / 'firmware/recovery/src/recovery_primary.c'),
        str(ROOT / 'firmware/ota/ota_image.c'), '-lcrypto', '-o', str(library)], check=True)
    fn = ctypes.CDLL(str(library)).recovery_primary_validate_migration
    fn.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
    artifacts = local_input(ROOT / 'experiments/common-candidate-0.6.0-20261023/artifacts')
    for name in ['migration-0.9.0.signed.bin', 'main-0.6.0.signed.bin', 'recovery-0.8.0.signed.bin']:
        blob = (artifacts / name).read_bytes()
        assert (fn(blob, len(blob), signed_hash(blob)) == 0) == name.startswith('migration')
