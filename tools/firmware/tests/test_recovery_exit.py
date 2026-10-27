"""Candidate recovery exit gesture; host only, no device/network/private key."""
from local_inputs import local_input, sdk_root
import ctypes
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'firmware/recovery/src'


def test_recovery_gesture_release_hold_busy_and_wrap(tmp_path):
    exe = tmp_path / 'recovery_exit'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=undefined',
        '-I', str(SOURCE), str(SOURCE / 'recovery_exit.c'),
        str(Path(__file__).with_name('recovery_exit_test.c')), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


def test_exit_guard_persists_partial_and_serializes_checkpoint_reboot(tmp_path):
    exe = tmp_path / 'recovery_exit_control'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=undefined',
        '-I', str(SOURCE), str(SOURCE / 'recovery_exit_control.c'),
        str(Path(__file__).with_name('recovery_exit_control_test.c')), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


def test_authenticated_primary_requires_main_vectors_and_exact_role(tmp_path):
    exe = tmp_path / 'recovery_primary_geometry'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=undefined',
        '-I', str(SOURCE), '-I', str(ROOT / 'firmware/src'), '-I', str(ROOT / 'firmware/ota'), str(SOURCE / 'recovery_primary.c'),
        str(Path(__file__).with_name('recovery_primary_geometry_test.c')), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


@pytest.fixture(scope='module')
def validator(tmp_path_factory):
    library = tmp_path_factory.mktemp('recovery_primary') / 'primary.so'
    subprocess.run(['cc', '-shared', '-fPIC', '-std=c11', '-Wno-deprecated-declarations',
        '-DOTA_IMAGE_AUTH_ONLY', '-DOTA_IMAGE_HOST', '-I', str(SOURCE), '-I', str(ROOT / 'firmware/src'),
        '-I', str(ROOT / 'firmware/ota'), str(SOURCE / 'recovery_primary.c'),
        str(ROOT / 'firmware/ota/ota_image.c'), '-lcrypto', '-o', str(library)], check=True)
    dll = ctypes.CDLL(str(library))
    dll.recovery_primary_validate.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    dll.recovery_primary_validate.restype = ctypes.c_int
    return dll.recovery_primary_validate


@pytest.mark.parametrize('path', [
    'experiments/release-055-20261021/ota/vimar-30805-0.5.5-0.reconstructed.bin',
    'experiments/scrivania-p031-acceptance-20261022/artifacts/main-0.5.7-9.signed.bin',
    'experiments/release-0.5.8-20261022T152907Z/artifacts/main-0.5.8.signed.bin',
    'experiments/release-0.5.8-20261022T152907Z/ota/vimar-30805-0.5.8.reconstructed.bin',
])
def test_only_four_exact_signed_normal_mains_are_eligible(validator, path):
    blob = local_input(ROOT / path).read_bytes()
    assert validator(blob, len(blob)) == 0
    # A complete-looking header/role never substitutes for cryptography.
    damaged = bytearray(blob)
    damaged[-1] ^= 1
    assert validator(bytes(damaged), len(damaged)) != 0
    assert validator(blob, len(blob) - 1) != 0


def test_real_signed_target2_outside_allowlist_is_not_main_authorization(validator):
    blob = local_input(ROOT / 'experiments/ota-split-staging-20261021/bench-pair-v4/ota/vimar-30805-0.5.7-8.reconstructed.bin').read_bytes()
    assert b'VIMAR30805\x02' in blob
    assert validator(blob, len(blob)) != 0


@pytest.mark.parametrize('path', [
    'experiments/release-0.5.8-20261022T152907Z/poltrona-migration/migration-0.8.1.signed.bin',
    'experiments/vimar-second-restore-20261020/restorer.signed.bin',
    'experiments/release-0.5.8-20261022T152907Z/powercut-v2/arm-artifacts/arm-0.0.2.signed.bin',
    'experiments/zigbee-ota-20261020/recovery-0.7.1.signed.bin',
])
def test_signed_migrator_restorer_diagnostic_and_recovery_are_not_manual_exit_main(validator, path):
    blob = local_input(ROOT / path).read_bytes()
    assert validator(blob, len(blob)) != 0
