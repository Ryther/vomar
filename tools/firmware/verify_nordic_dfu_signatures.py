#!/usr/bin/env python3
"""Verify legacy Nordic Secure DFU init-packet signatures.

Nordic's SDK stores P-256 public-key coordinates and raw ECDSA r/s values as
two independently little-endian 32-byte integers. The signature covers the
serialized InitCommand, not its enclosing Command message.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Iterator

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils


def read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
        if shift >= 64:
            break
    raise ValueError("invalid protobuf varint")


def protobuf_fields(data: bytes) -> Iterator[tuple[int, int, int | bytes]]:
    offset = 0
    while offset < len(data):
        tag, offset = read_varint(data, offset)
        field_number = tag >> 3
        wire_type = tag & 7
        if field_number == 0:
            raise ValueError("invalid protobuf field number 0")
        if wire_type == 0:
            value, offset = read_varint(data, offset)
        elif wire_type == 2:
            size, offset = read_varint(data, offset)
            end = offset + size
            if end > len(data):
                raise ValueError("truncated protobuf field")
            value = data[offset:end]
            offset = end
        else:
            raise ValueError(f"unsupported protobuf wire type {wire_type}")
        yield field_number, wire_type, value


def length_delimited_field(data: bytes, number: int) -> bytes:
    matches = [
        value
        for field_number, wire_type, value in protobuf_fields(data)
        if field_number == number and wire_type == 2
    ]
    if len(matches) != 1 or not isinstance(matches[0], bytes):
        raise ValueError(f"expected exactly one length-delimited field {number}")
    return matches[0]


def decode_signed_packet(data: bytes) -> tuple[bytes, bytes]:
    signed_command = length_delimited_field(data, 2)
    command = length_delimited_field(signed_command, 1)
    signature = length_delimited_field(signed_command, 3)
    init_command = length_delimited_field(command, 2)
    if len(signature) != 64:
        raise ValueError(f"expected a 64-byte ECDSA signature, got {len(signature)}")
    return init_command, signature


def public_key_from_little_endian(raw: bytes):
    if len(raw) != 64:
        raise ValueError(f"expected a 64-byte public key, got {len(raw)}")
    x = int.from_bytes(raw[:32], "little")
    y = int.from_bytes(raw[32:], "little")
    return ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()


def verify_packet(path: Path, public_key) -> dict[str, object]:
    init_command, signature = decode_signed_packet(path.read_bytes())
    r = int.from_bytes(signature[:32], "little")
    s = int.from_bytes(signature[32:], "little")
    verified = False
    if public_key is not None:
        try:
            public_key.verify(
                utils.encode_dss_signature(r, s),
                init_command,
                ec.ECDSA(hashes.SHA256()),
            )
            verified = True
        except InvalidSignature:
            pass
    return {
        "path": str(path),
        "init_command_size": len(init_command),
        "init_command_sha256": hashlib.sha256(init_command).hexdigest(),
        "verified": verified,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-key-le", required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("packets", nargs="+", type=Path)
    args = parser.parse_args()

    try:
        raw_key = bytes.fromhex(args.public_key_le)
    except ValueError as exc:
        parser.error(f"invalid --public-key-le hex: {exc}")

    public_key = None
    key_error = None
    try:
        public_key = public_key_from_little_endian(raw_key)
    except ValueError as exc:
        key_error = str(exc)

    report = {
        "public_key_le": raw_key.hex(),
        "public_key_valid_p256_point": public_key is not None,
        "packets": [verify_packet(path, public_key) for path in args.packets],
    }
    if key_error:
        report["public_key_error"] = key_error

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for packet in report["packets"]:
            status = "VERIFIED" if packet["verified"] else "INVALID"
            print(f"{status}\t{packet['path']}")

    return 0 if all(packet["verified"] for packet in report["packets"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
