"""Compile the real bridge policy and OTA parser; simulate retained NVS records.

Removing identity/CRC/state checks must fail these tests. The reset model exposes
old/new/torn records to the policy; NVS atomic record selection and physical copy
qualification remain integration responsibilities.
"""
import ctypes as C
from pathlib import Path
import struct
import subprocess
import zlib

import pytest

ROOT = Path(__file__).resolve().parents[3]
CHECKPOINT_SIZE = 128


class Identity(C.Structure):
    _fields_ = [("uid", C.c_uint32 * 2),
                ("loader_digest", C.c_uint8 * 32),
                ("primary_digest", C.c_uint8 * 32),
                ("recovery_digest", C.c_uint8 * 32),
                ("primary_size", C.c_uint32)]


class Transaction(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in (
        "format_version", "generation", "state", "stage_start", "stage_end",
        "candidate_size", "signed_image_size")]
    _fields_ += [("candidate_digest", C.c_uint8 * 32),
                 ("final_digest", C.c_uint8 * 32),
                 ("second_start", C.c_uint32), ("second_end", C.c_uint32),
                 ("recovery_digest", C.c_uint8 * 32),
                 ("loader_digest", C.c_uint8 * 32)]


@pytest.fixture(scope="module")
def policy(tmp_path_factory):
    out = tmp_path_factory.mktemp("legacy-bridge-policy") / "policy.so"
    subprocess.run([
        "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-fPIC", "-shared",
        "-fsanitize=undefined", "-fno-sanitize-recover=undefined",
        "-I", str(ROOT / "firmware/ota_migration/src"),
        "-I", str(ROOT / "firmware/ota"),
        str(ROOT / "firmware/ota_migration/src/legacy_bridge_policy.c"),
        str(ROOT / "firmware/ota/ota_transaction.c"), "-o", str(out),
    ], check=True, capture_output=True)
    lib = C.CDLL(str(out))
    lib.legacy_bridge_checkpoint_encode.argtypes = [C.POINTER(Identity), C.c_void_p, C.c_size_t]
    lib.legacy_bridge_checkpoint_decode.argtypes = [C.c_void_p, C.c_size_t, C.POINTER(Identity)]
    lib.legacy_bridge_admit.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p, C.c_size_t,
                                      C.POINTER(Identity), C.POINTER(C.c_bool), C.POINTER(C.c_bool)]
    lib.ota_transaction_encode.argtypes = [C.POINTER(Transaction), C.c_void_p, C.c_size_t]
    return lib


def identity():
    result = Identity(uid=(0x11223344, 0x55667788), primary_size=390624)
    for name, start in (("loader_digest", 1), ("primary_digest", 33), ("recovery_digest", 65)):
        getattr(result, name)[:] = range(start, start + 32)
    return result


def checkpoint(policy, expected=None):
    expected = identity() if expected is None else expected
    result = C.create_string_buffer(CHECKPOINT_SIZE)
    assert policy.legacy_bridge_checkpoint_encode(C.byref(expected), result, len(result)) == 0
    return result.raw


def transaction(policy, state=4, version=1, expected=None):
    expected = identity() if expected is None else expected
    tx = Transaction(format_version=version, generation=1, state=state,
                     stage_start=0x70000, stage_end=0xAE000,
                     candidate_size=246564, signed_image_size=expected.primary_size)
    tx.candidate_digest[0] = 1
    tx.final_digest[:] = expected.primary_digest
    tx.second_start, tx.second_end = 0xE4000, 0xEF000
    tx.recovery_digest[0], tx.loader_digest[0] = 1, 2
    out = C.create_string_buffer(104 if version == 1 else 176)
    assert policy.ota_transaction_encode(C.byref(tx), out, len(out)) == 0
    return out.raw


def crc(record):
    return bytes(record[:-4]) + struct.pack("<I", zlib.crc32(record[:-4]))


def admit(policy, tx=None, cp=None, expected=None, *, tx_size=None, cp_size=None):
    expected = identity() if expected is None else expected
    needs, clear = C.c_bool(True), C.c_bool(True)
    inputs = (None if tx is None else memoryview(tx).tobytes(),
              None if cp is None else memoryview(cp).tobytes(), bytes(expected))
    rc = policy.legacy_bridge_admit(
        tx, (0 if tx is None else len(tx)) if tx_size is None else tx_size,
        cp, (0 if cp is None else len(cp)) if cp_size is None else cp_size,
        C.byref(expected), C.byref(needs), C.byref(clear))
    assert inputs == (tx, cp, bytes(expected))
    if rc:
        assert not needs.value and not clear.value
    return rc, needs.value, clear.value


def test_checkpoint_roundtrip_and_independent_wire_format(policy):
    expected = identity()
    cp = checkpoint(policy, expected)
    assert len(cp) == CHECKPOINT_SIZE
    assert struct.unpack_from("<4I", cp) == (0x3143424C, 1, 128, 0)
    assert cp[16:24] == struct.pack("<2I", *expected.uid)
    assert cp[24:56] == bytes(expected.loader_digest)
    assert cp[56:88] == bytes(expected.primary_digest)
    assert cp[88:120] == bytes(expected.recovery_digest)
    assert struct.unpack_from("<I", cp, 120)[0] == expected.primary_size
    assert cp == crc(cp)
    decoded = Identity()
    assert policy.legacy_bridge_checkpoint_decode(cp, len(cp), C.byref(decoded)) == 0
    assert bytes(decoded) == bytes(expected)


@pytest.mark.parametrize("state", [2, 3, 4], ids=["pending", "installing", "complete"])
def test_installed_self_transaction_requests_checkpoint_before_deletion(policy, state):
    assert admit(policy, transaction(policy, state=state)) == (0, True, True)


def test_restart_before_and_after_journal_deletion_uses_same_checkpoint(policy):
    tx, cp = transaction(policy), checkpoint(policy)
    assert admit(policy, tx, cp) == (0, False, True)
    assert admit(policy, None, cp) == (0, False, False)
    assert admit(policy, None, None)[0] != 0
    # Checkpoint remains authoritative across later boot-flag/recovery-copy cuts.
    for _ in range(16):
        assert admit(policy, None, cp) == (0, False, False)


def test_every_torn_or_corrupt_checkpoint_fails_before_transaction_deletion(policy):
    cp, tx = checkpoint(policy), transaction(policy)
    for cut in range(len(cp)):
        assert admit(policy, tx, cp[:cut])[0] != 0
        torn = cp[:cut] + b"\xff" * (len(cp) - cut)
        assert admit(policy, tx, torn)[0] != 0
        assert admit(policy, None, torn)[0] != 0
    for index in range(len(cp)):
        altered = bytearray(cp)
        altered[index] ^= 1
        assert admit(policy, tx, bytes(altered))[0] != 0
        decoded = identity()
        assert policy.legacy_bridge_checkpoint_decode(bytes(altered), len(altered), C.byref(decoded)) != 0
        assert bytes(decoded) == bytes(Identity())


@pytest.mark.parametrize("field", ["uid0", "uid1", "loader_digest", "primary_digest", "recovery_digest", "primary_size"])
def test_matching_transaction_never_overrides_contradictory_checkpoint(policy, field):
    stale = identity()
    if field.startswith("uid"):
        stale.uid[int(field[-1])] ^= 1
    elif field == "primary_size":
        stale.primary_size -= 1
    else:
        getattr(stale, field)[17] ^= 1
    cp = checkpoint(policy, stale)
    assert admit(policy, transaction(policy), cp)[0] != 0
    assert admit(policy, None, cp)[0] != 0


@pytest.mark.parametrize("offset", [0, 4, 8, 12])
def test_checkpoint_rejects_semantic_header_damage_even_with_valid_crc(policy, offset):
    altered = bytearray(checkpoint(policy))
    altered[offset] ^= 1
    assert admit(policy, transaction(policy), crc(altered))[0] != 0


@pytest.mark.parametrize("damage", ["downloading", "v2", "wrong-hash", "wrong-size",
                                   "bad-state", "generation-zero", "bad-magic", "bad-version",
                                   "bad-length", "unaligned-stage", "stage-overflow", "candidate-overflow"])
def test_wrong_or_malformed_transactions_reject_even_with_matching_checkpoint(policy, damage):
    if damage == "downloading":
        tx = transaction(policy, state=1)
    elif damage == "v2":
        tx = transaction(policy, version=2)
    else:
        tx = bytearray(transaction(policy))
        offsets = {"wrong-hash": 68, "wrong-size": 32, "bad-state": 16,
                   "generation-zero": 12, "bad-magic": 0, "bad-version": 4,
                   "bad-length": 8, "unaligned-stage": 20, "stage-overflow": 24,
                   "candidate-overflow": 28}
        offset = offsets[damage]
        value = {"bad-state": 99, "generation-zero": 0, "stage-overflow": 0xAF000,
                 "candidate-overflow": 0xFFFFFFFF}.get(damage)
        if value is None:
            tx[offset] ^= 1
        else:
            struct.pack_into("<I", tx, offset, value)
        tx = crc(tx)
    assert admit(policy, tx)[0] != 0
    assert admit(policy, tx, checkpoint(policy))[0] != 0


def test_every_torn_or_corrupt_transaction_rejects(policy):
    tx, cp = transaction(policy), checkpoint(policy)
    for cut in range(len(tx)):
        assert admit(policy, tx[:cut], cp)[0] != 0
        assert admit(policy, tx[:cut] + b"\xff" * (len(tx) - cut), cp)[0] != 0
    for index in range(len(tx)):
        altered = bytearray(tx)
        altered[index] ^= 1
        assert admit(policy, bytes(altered), cp)[0] != 0


@pytest.mark.parametrize("damage", ["uid-zero", "uid-erased", "loader-zero", "primary-zero",
                                   "recovery-zero", "size-zero", "size-overflow"])
def test_invalid_expected_identity_fails_closed_without_output_writes(policy, damage):
    expected = identity()
    if damage.startswith("uid"):
        expected.uid[:] = (0, 0) if damage == "uid-zero" else (0xFFFFFFFF, 0xFFFFFFFF)
    elif damage.startswith("size"):
        expected.primary_size = 0 if damage == "size-zero" else 0xFFFFFFFF
    else:
        getattr(expected, damage.split("-")[0] + "_digest")[:] = bytes(32)
    out = C.create_string_buffer(b"\xa5" * 128, 128)
    assert policy.legacy_bridge_checkpoint_encode(C.byref(expected), out, len(out)) != 0
    assert out.raw == b"\xa5" * 128
    assert admit(policy, transaction(policy), expected=expected)[0] != 0


def test_pointer_size_and_output_argument_errors(policy):
    cp, tx = checkpoint(policy), transaction(policy)
    for tx_ptr, tx_size, cp_ptr, cp_size in [
        (None, 104, cp, 128), (tx, 0, cp, 128), (tx, 104, None, 128),
        (tx, 104, cp, 0), (None, 0, b"", 0), (b"", 0, cp, 128),
        (tx, 103, cp, 128), (tx, 105, cp, 128), (None, 0, cp, 129),
    ]:
        assert admit(policy, tx_ptr, cp_ptr, tx_size=tx_size, cp_size=cp_size)[0] != 0
    expected = identity()
    for size in (0, 127, 129):
        out = C.create_string_buffer(b"\xa5" * 129, 129)
        assert policy.legacy_bridge_checkpoint_encode(C.byref(expected), out, size) != 0
        assert out.raw == b"\xa5" * 129
    assert policy.legacy_bridge_checkpoint_encode(None, None, 128) != 0
    assert policy.legacy_bridge_checkpoint_encode(C.byref(expected), None, 128) != 0
    assert policy.legacy_bridge_checkpoint_decode(cp, 128, None) != 0
    decoded = identity()
    assert policy.legacy_bridge_checkpoint_decode(None, 128, C.byref(decoded)) != 0
    assert bytes(decoded) == bytes(Identity())
    for expected_ptr, needs_ptr, clear_ptr in [
        (None, C.pointer(C.c_bool(True)), C.pointer(C.c_bool(True))),
        (C.pointer(expected), None, C.pointer(C.c_bool(True))),
        (C.pointer(expected), C.pointer(C.c_bool(True)), None),
    ]:
        assert policy.legacy_bridge_admit(tx, 104, None, 0, expected_ptr, needs_ptr, clear_ptr) != 0
        assert needs_ptr is None or not needs_ptr.contents.value
        assert clear_ptr is None or not clear_ptr.contents.value
    aliased = C.c_bool(True)
    assert policy.legacy_bridge_admit(tx, 104, None, 0, C.byref(expected),
                                      C.byref(aliased), C.byref(aliased)) != 0
    assert not aliased.value
