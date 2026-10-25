"""Legacy bridge input/signature and exact OTA reconstruction boundaries."""
import hashlib
import json
import lzma
import struct

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

from tools.firmware import build_legacy_zigbee_bridge as builder


def sha(blob):
    return hashlib.sha256(blob).digest()


def area(magic, entries):
    content = b"".join(struct.pack("<HH", tag, len(value)) + value for tag, value in entries)
    return struct.pack("<HH", magic, 4 + len(content)) + content


@pytest.fixture
def key():
    return ec.generate_private_key(ec.SECP256R1())


def signed(key, *, base=0xc000, version=(0, 6, 3, 0), target=b"VIMAR30805\x01",
           role=None, payload=None, compression=None):
    payload = payload if payload is not None else struct.pack("<II", 0x20040000, base + 513) + b"code" * 40
    protected = [] if target is None else [(0xa0, target)]
    if role is not None:
        protected.append((0xa1, bytes([role])))
    if compression is not None:
        ordinary, plain_payload = compression
        plain_digest = sha(ordinary[:512 + len(plain_payload) + struct.unpack_from("<H", ordinary, 10)[0]])
        protected.extend([(0x70, struct.pack("<I", len(plain_payload))), (0x71, plain_digest),
                          (0x72, key.sign(plain_digest, ec.ECDSA(utils.Prehashed(hashes.SHA256()))))])
    protected = area(0x6908, protected) if protected else b""
    header = bytearray(512)
    struct.pack_into("<IIHHII", header, 0, 0x96f3b83d, 0, 512, len(protected), len(payload), 0xc00 if compression else 0)
    struct.pack_into("<BBHI", header, 20, *version)
    authenticated = bytes(header) + payload + protected
    digest = sha(authenticated)
    public = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return authenticated + area(0x6907, [(1, sha(public)), (0x10, digest),
        (0x22, key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256()))))])


def compressed_pair(key):
    payload = struct.pack("<II", 0x20040000, 0xc201) + b"bridge" * 40
    ordinary = signed(key, payload=payload)
    stream = b"\x06\x5d" + lzma.compress(payload, format=lzma.FORMAT_RAW, filters=[
        {"id": lzma.FILTER_ARMTHUMB}, {"id": lzma.FILTER_LZMA2, "dict_size": 32768}])
    return ordinary, signed(key, payload=stream, compression=(ordinary, payload))


def test_legacy_source_accepts_old_untagged_image_and_binds_signed_region(key):
    blob = signed(key, base=0xb0000, version=(0, 7, 1, 0), target=None)
    actual = builder.legacy_image_metadata(blob, key.public_key(), base=0xb0000,
        capacity=0x40000, version="0.7.1")
    assert actual["signedRegionSha256"] == sha(blob[:512 + 168]).hex()
    assert actual["profile"] == 1


@pytest.mark.parametrize("damage", ["role", "profile2", "signature", "payload", "version", "reset"])
def test_rejects_wrong_legacy_identity_or_signature(key, damage):
    options = dict(base=0xb0000, version=(0, 7, 1, 0), target=None)
    if damage == "role": options["role"] = 2
    if damage == "profile2": options["target"] = b"VIMAR30805\x02"
    if damage == "version": options["version"] = (0, 7, 2, 0)
    if damage == "reset": options["payload"] = struct.pack("<II", 0x20040000, 0xc201) + b"x" * 100
    blob = bytearray(signed(key, **options))
    if damage == "signature": blob[-1] ^= 1
    if damage == "payload": blob[525] ^= 1
    with pytest.raises(ValueError):
        builder.legacy_image_metadata(bytes(blob), key.public_key(), base=0xb0000,
            capacity=0x40000, version="0.7.1")


def test_bridge_requires_explicit_profile1_target(key):
    blob = signed(key, target=None)
    with pytest.raises(ValueError, match="target"):
        builder.legacy_image_metadata(blob, key.public_key(), base=0xc000,
            capacity=0xa2000, version="0.6.3", require_target=True)


def test_carrier_binds_ordinary_bytes_and_legacy_wire_identity(key):
    ordinary, compressed = compressed_pair(key)
    ota, metadata = builder.legacy_carrier(compressed, ordinary, key.public_key())
    assert len(ota) == 66 + len(compressed)
    assert struct.unpack_from("<I", ota, 0)[0] == 0x0beef11e
    assert struct.unpack_from("<HHI", ota, 10) == (0xfff1, 0x3085, 0x00060300)
    assert ota[66:] == compressed
    payload_size = struct.unpack_from("<I", ordinary, 12)[0]
    protected_size = struct.unpack_from("<H", ordinary, 10)[0]
    assert metadata["signedRegionSha256"] == sha(ordinary[:512 + payload_size + protected_size]).hex()


@pytest.mark.parametrize("damage", ["signature", "profile2", "role", "wrong-payload", "wrong-ordinary"])
def test_carrier_rejects_wrong_identity_corruption_or_reconstruction(key, damage):
    ordinary, compressed = compressed_pair(key)
    if damage == "signature": compressed = compressed[:-1] + bytes([compressed[-1] ^ 1])
    elif damage == "wrong-ordinary": ordinary = signed(key)
    else:
        payload = ordinary[512:512 + struct.unpack_from("<I", ordinary, 12)[0]]
        stream = b"\x06\x5d" + lzma.compress(payload if damage != "wrong-payload" else b"other", format=lzma.FORMAT_RAW,
            filters=[{"id": lzma.FILTER_ARMTHUMB}, {"id": lzma.FILTER_LZMA2, "dict_size": 32768}])
        compressed = signed(key, target=b"VIMAR30805\x02" if damage == "profile2" else b"VIMAR30805\x01",
            role=1 if damage == "role" else None, payload=stream, compression=(ordinary, payload))
    with pytest.raises(ValueError):
        builder.legacy_carrier(compressed, ordinary, key.public_key())


@pytest.fixture
def candidate(tmp_path, key):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    recovery = signed(key, base=0xb0000, version=(0, 8, 3, 0), target=b"VIMAR30805\x02", role=2)
    (artifacts / "recovery.signed.bin").write_bytes(recovery)
    config = b"".join((name + "=" + value + "\n").encode() for name, value in {
        "CONFIG_BT": "y", "CONFIG_BT_SMP": "y", "CONFIG_BT_SETTINGS": "y", "CONFIG_SETTINGS": "y",
        "CONFIG_SETTINGS_NVS": "y", "CONFIG_NVS": "y", "CONFIG_BT_MAX_PAIRED": "8", "CONFIG_BT_MAX_CONN": "1",
        "CONFIG_MCUMGR_TRANSPORT_BT": "y", "CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN": "y"}.items())
    (artifacts / "recovery.config").write_bytes(config)
    manifest = dict(schema_version=1, kind="unqualified-typed-common-candidate", model="VIMAR30805",
        versions={"recovery": "0.8.3"}, artifacts={"recovery": dict(path="artifacts/recovery.signed.bin",
        sha256=sha(recovery).hex(), size=len(recovery))}, native={"recovery": dict(config_sha256=sha(config).hex())},
        loader_contracts=[{"kind": "common-code44k-anchor-v1", "sha256": "00" * 32}] + [
            {"kind": "legacy-full48k-sha256", "sha256": str(i) * 64} for i in range(1, 4)])
    path = tmp_path / "candidate-manifest.json"
    path.write_text(json.dumps(manifest))
    return path, manifest


def test_candidate_freezes_signed_recovery_and_only_three_legacy_loaders(candidate, key):
    path, _ = candidate
    actual = builder.validate_candidate(path, key.public_key())
    assert actual["allowed_loaders"] == [str(i) * 64 for i in range(1, 4)]
    assert actual["recovery_bytes"] == (path.parent / "artifacts/recovery.signed.bin").read_bytes()


@pytest.mark.parametrize("damage", ["recovery-sha", "config-sha", "capacity", "eviction", "loaders", "target-signature", "target-role", "target-profile"])
def test_candidate_rejects_unbound_or_incompatible_inputs(candidate, key, damage):
    path, manifest = candidate
    if damage == "recovery-sha": manifest["artifacts"]["recovery"]["sha256"] = "00" * 32
    elif damage == "config-sha": manifest["native"]["recovery"]["config_sha256"] = "00" * 32
    elif damage == "loaders": manifest["loader_contracts"].pop()
    elif damage.startswith("target-"):
        if damage == "target-signature":
            blob = bytearray((path.parent / "artifacts/recovery.signed.bin").read_bytes()); blob[-1] ^= 1
        else:
            blob = signed(key, base=0xb0000, version=(0, 8, 3, 0),
                target=b"VIMAR30805\x01" if damage == "target-profile" else b"VIMAR30805\x02",
                role=1 if damage == "target-role" else 2)
        (path.parent / "artifacts/recovery.signed.bin").write_bytes(blob)
        manifest["artifacts"]["recovery"]["sha256"] = sha(blob).hex()
        manifest["artifacts"]["recovery"]["size"] = len(blob)
    else:
        config = path.parent / "artifacts/recovery.config"
        data = config.read_bytes().replace(b"CONFIG_BT_MAX_PAIRED=8", b"CONFIG_BT_MAX_PAIRED=1") if damage == "capacity" else config.read_bytes() + b"CONFIG_BT_KEYS_OVERWRITE_OLDEST=y\n"
        config.write_bytes(data); manifest["native"]["recovery"]["config_sha256"] = sha(data).hex()
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError): builder.validate_candidate(path, key.public_key())


def test_existing_output_rejected_before_reading_build_inputs(tmp_path):
    with pytest.raises(ValueError, match="NEW"):
        builder.build(tmp_path, tmp_path / "absent-candidate", tmp_path / "absent-recovery")


def test_immutable_input_output_rejected_before_reading_build_inputs(tmp_path):
    with pytest.raises(ValueError, match="immutable"):
        builder.build(builder.ROOT / "inputs/forbidden-bridge-output", tmp_path / "absent-candidate", tmp_path / "absent-recovery")
