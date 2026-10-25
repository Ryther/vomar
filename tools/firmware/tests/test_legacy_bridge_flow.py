"""Native persistence orchestration with reset/fault injection at each boundary."""
import ctypes as C
import errno
from pathlib import Path
import subprocess

import pytest

from tools.firmware.tests.test_legacy_bridge_policy import Identity, Transaction, identity

ROOT = Path(__file__).resolve().parents[3]
LOAD = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_int, C.c_void_p, C.c_size_t,
                  C.POINTER(C.c_size_t))
SAVE = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_void_p, C.c_size_t)
OP = C.CFUNCTYPE(C.c_int, C.c_void_p)


class IO(C.Structure):
    _fields_ = [("ctx", C.c_void_p), ("load", LOAD), ("save_checkpoint", SAVE),
                ("clear_transaction", OP), ("verify_legacy_recovery", OP),
                ("clear_boot_request", OP)]


@pytest.fixture(scope="module")
def flow(tmp_path_factory):
    out = tmp_path_factory.mktemp("legacy-bridge-flow") / "flow.so"
    subprocess.run([
        "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-fPIC", "-shared",
        "-fsanitize=undefined", "-fno-sanitize-recover=undefined",
        "-I", str(ROOT / "firmware/ota_migration/src"),
        "-I", str(ROOT / "firmware/ota"),
        str(ROOT / "firmware/ota_migration/src/legacy_bridge_flow.c"),
        str(ROOT / "firmware/ota_migration/src/legacy_bridge_policy.c"),
        str(ROOT / "firmware/ota/ota_transaction.c"), "-o", str(out),
    ], check=True, capture_output=True)
    lib = C.CDLL(str(out))
    lib.legacy_bridge_flow_prepare.argtypes = [C.POINTER(Identity), C.POINTER(IO)]
    lib.legacy_bridge_checkpoint_encode.argtypes = [C.POINTER(Identity), C.c_void_p, C.c_size_t]
    lib.ota_transaction_encode.argtypes = [C.POINTER(Transaction), C.c_void_p, C.c_size_t]
    return lib


def checkpoint(flow, expected=None):
    expected = identity() if expected is None else expected
    out = C.create_string_buffer(128)
    assert flow.legacy_bridge_checkpoint_encode(C.byref(expected), out, 128) == 0
    return out.raw


def transaction(flow, *, state=4, expected=None):
    expected = identity() if expected is None else expected
    tx = Transaction(format_version=1, generation=1, state=state,
                     stage_start=0x70000, stage_end=0xAE000,
                     candidate_size=246564, signed_image_size=expected.primary_size)
    tx.candidate_digest[0] = 1
    tx.final_digest[:] = expected.primary_digest
    out = C.create_string_buffer(104)
    assert flow.ota_transaction_encode(C.byref(tx), out, 104) == 0
    return out.raw


class Storage:
    """Callbacks retain committed bytes when a simulated reset returns an error."""
    def __init__(self, flow, *, cp=b"", tx=None):
        self.flow = flow
        self.tx = transaction(flow) if tx is None else tx
        self.cp = cp
        self.boot_request = True
        self.old_recovery_valid = True
        self.events = []
        self.fail_before = {}
        self.fail_after = {}
        self.bad_load = {}
        self.keep_transaction = False
        self.torn_save = False
        self.saved_override = None
        self.callbacks = (LOAD(self.load), SAVE(self.save), OP(self.clear),
                          OP(self.verify), OP(self.boot))
        self.io = IO(None, *self.callbacks)

    def event(self, name):
        self.events.append(name)
        return name, self.events.count(name)

    def load(self, _ctx, key, out, capacity, out_len):
        name = "load_tx" if key == 0 else "load_cp"
        event = self.event(name)
        status = self.fail_before.get(event, 0)
        if status:
            return status
        data = self.tx if key == 0 else self.cp
        fault = self.bad_load.get(event)
        if fault == "missing-length":
            return 0
        if fault == "oversize":
            out_len[0] = capacity + 1
            return 0
        if fault == "corrupt":
            data = data[:-1] + bytes([data[-1] ^ 1])
        if len(data) <= capacity:
            C.memmove(out, data, len(data))
        out_len[0] = len(data)
        return 0

    def save(self, _ctx, record, size):
        event = self.event("save")
        if event in self.fail_before:
            return self.fail_before[event]
        data = C.string_at(record, size)
        self.cp = self.saved_override if self.saved_override is not None else data
        if self.torn_save:
            self.cp = self.cp[:64] + b"\xff" * 64
        return self.fail_after.get(event, 0)

    def clear(self, _ctx):
        event = self.event("clear")
        if event in self.fail_before:
            return self.fail_before[event]
        if not self.keep_transaction:
            self.tx = b""
        return self.fail_after.get(event, 0)

    def verify(self, _ctx):
        event = self.event("verify")
        return self.fail_before.get(event, 0) or (0 if self.old_recovery_valid else -errno.EPERM)

    def boot(self, _ctx):
        event = self.event("boot")
        if event in self.fail_before:
            return self.fail_before[event]
        self.boot_request = False
        return self.fail_after.get(event, 0)

    def prepare(self, expected=None):
        expected = identity() if expected is None else expected
        return self.flow.legacy_bridge_flow_prepare(C.byref(expected), C.byref(self.io))

    def restart(self):
        self.events.clear()
        self.fail_before.clear()
        self.fail_after.clear()
        self.bad_load.clear()


@pytest.mark.parametrize("state", [2, 3, 4])
def test_fresh_flow_authenticates_old_recovery_and_readbacks_before_mutations(flow, state):
    storage = Storage(flow, tx=transaction(flow, state=state))
    assert storage.prepare() == 0
    assert storage.events == ["load_tx", "load_cp", "verify", "save", "load_cp",
                              "clear", "load_tx", "boot"]
    assert storage.cp == checkpoint(flow) and storage.tx == b"" and not storage.boot_request


@pytest.mark.parametrize("retained_tx", [True, False])
def test_matching_checkpoint_resumes_partial_recovery_without_old_rec_validation(flow, retained_tx):
    storage = Storage(flow, cp=checkpoint(flow), tx=None if retained_tx else b"")
    storage.old_recovery_valid = False
    assert storage.prepare() == 0
    assert storage.events == (["load_tx", "load_cp", "clear", "load_tx", "boot"]
                              if retained_tx else ["load_tx", "load_cp", "boot"])
    storage.restart()
    assert storage.prepare() == 0
    assert storage.events == ["load_tx", "load_cp", "boot"]


@pytest.mark.parametrize("damage", ["missing", "downloading", "wrong-tx", "bad-tx-crc",
                                   "wrong-checkpoint", "bad-checkpoint-crc"])
def test_invalid_authorization_never_mutates_anything(flow, damage):
    storage = Storage(flow)
    wrong = identity()
    wrong.primary_digest[17] ^= 1
    if damage == "missing":
        storage.tx = b""
    elif damage == "downloading":
        storage.tx = transaction(flow, state=1)
    elif damage == "wrong-tx":
        storage.tx = transaction(flow, expected=wrong)
    elif damage == "bad-tx-crc":
        storage.tx = storage.tx[:-1] + bytes([storage.tx[-1] ^ 1])
    elif damage == "wrong-checkpoint":
        storage.cp = checkpoint(flow, wrong)
    else:
        storage.cp = checkpoint(flow)[:-1] + b"\x00"
    before = storage.tx, storage.cp, storage.boot_request
    assert storage.prepare() < 0
    assert storage.events == ["load_tx", "load_cp"]
    assert (storage.tx, storage.cp, storage.boot_request) == before


def test_old_recovery_must_authenticate_before_first_checkpoint(flow):
    storage = Storage(flow)
    storage.old_recovery_valid = False
    assert storage.prepare() == -errno.EPERM
    assert storage.events == ["load_tx", "load_cp", "verify"]
    assert storage.cp == b"" and storage.tx


@pytest.mark.parametrize("boundary", ["before-save", "after-save", "checkpoint-readback",
                                     "before-delete", "after-delete", "transaction-readback",
                                     "before-boot", "after-boot"])
def test_interruption_at_each_persistence_boundary_is_resumable(flow, boundary):
    storage = Storage(flow)
    location = {"before-save": ("save", 1), "after-save": ("save", 1),
                "checkpoint-readback": ("load_cp", 2), "before-delete": ("clear", 1),
                "after-delete": ("clear", 1), "transaction-readback": ("load_tx", 2),
                "before-boot": ("boot", 1), "after-boot": ("boot", 1)}[boundary]
    target = storage.fail_after if boundary.startswith("after-") else storage.fail_before
    target[location] = -errno.EIO
    assert storage.prepare() == -errno.EIO
    if boundary in ("before-save", "after-save", "checkpoint-readback", "before-delete"):
        assert storage.tx
    if boundary != "before-save":
        assert storage.cp == checkpoint(flow)
    if boundary not in ("before-boot", "after-boot"):
        assert "boot" not in storage.events
    storage.restart()
    # Old REC may already be partly overwritten only after a successful flow.
    storage.old_recovery_valid = boundary == "before-save"
    assert storage.prepare() == 0
    assert storage.cp == checkpoint(flow) and not storage.tx and not storage.boot_request
    assert ("verify" in storage.events) == (boundary == "before-save")


@pytest.mark.parametrize("damage", ["torn-save", "wrong-save", "corrupt-readback", "oversize-readback"])
def test_checkpoint_must_read_back_exactly_before_journal_deletion(flow, damage):
    storage = Storage(flow)
    if damage == "torn-save":
        storage.torn_save = True
    elif damage == "wrong-save":
        wrong = identity()
        wrong.uid[1] ^= 1
        storage.saved_override = checkpoint(flow, wrong)
    else:
        storage.bad_load[("load_cp", 2)] = "corrupt" if damage == "corrupt-readback" else "oversize"
    assert storage.prepare() < 0
    assert storage.tx and storage.boot_request
    assert storage.events == ["load_tx", "load_cp", "verify", "save", "load_cp"]
    storage.restart()
    if damage in ("torn-save", "wrong-save"):
        assert storage.prepare() < 0
        assert storage.events == ["load_tx", "load_cp"]
    else:
        storage.old_recovery_valid = False
        assert storage.prepare() == 0


def test_successful_deletion_callback_still_requires_absent_readback(flow):
    storage = Storage(flow)
    storage.keep_transaction = True
    assert storage.prepare() < 0
    assert storage.tx and storage.cp == checkpoint(flow) and storage.boot_request
    assert storage.events[-2:] == ["clear", "load_tx"]
    assert "boot" not in storage.events


@pytest.mark.parametrize("key", ["load_tx", "load_cp"])
@pytest.mark.parametrize("fault", ["failure", "positive-status", "oversize", "missing-length"])
def test_load_errors_and_invalid_lengths_stop_before_mutation(flow, key, fault):
    storage = Storage(flow)
    if fault in ("failure", "positive-status"):
        storage.fail_before[(key, 1)] = -errno.EIO if fault == "failure" else 1
    else:
        storage.bad_load[(key, 1)] = fault
    assert storage.prepare() < 0
    assert all(name.startswith("load_") for name in storage.events)
    assert storage.tx and not storage.cp and storage.boot_request


@pytest.mark.parametrize("name", ["verify", "save", "clear", "boot"])
def test_positive_callback_status_is_failure_and_cannot_authorize_copy(flow, name):
    storage = Storage(flow)
    storage.fail_before[(name, 1)] = 1
    assert storage.prepare() == -errno.EIO
    assert storage.events[-1] == name


@pytest.mark.parametrize("field", ["load", "save_checkpoint", "clear_transaction",
                                  "verify_legacy_recovery", "clear_boot_request"])
def test_missing_callbacks_fail_before_storage_access(flow, field):
    storage = Storage(flow)
    setattr(storage.io, field, LOAD() if field == "load" else SAVE() if field == "save_checkpoint" else OP())
    assert storage.prepare() == -errno.EINVAL
    assert not storage.events


def test_bad_identity_or_null_io_fails_before_storage_access(flow):
    storage = Storage(flow)
    expected = identity()
    expected.primary_size = 0
    assert storage.prepare(expected) == -errno.EINVAL
    assert storage.events == []
    assert flow.legacy_bridge_flow_prepare(None, C.byref(storage.io)) == -errno.EINVAL
    assert flow.legacy_bridge_flow_prepare(C.byref(identity()), None) == -errno.EINVAL
