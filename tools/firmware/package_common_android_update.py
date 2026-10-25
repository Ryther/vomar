#!/usr/bin/env python3
"""Build a qualified common schema2 release; reads explicit artifacts, never hardware.

--release is a release-only descriptor, with main and optional recovery/migration
path+sha256 references. Keys are explicit; no production key is selected by default.
The descriptor contains no device names, addresses or identities. Qualification
must bind every component and the finite loader allowlist to completed checks.
"""
import argparse
import hashlib
import io
import json
import lzma
from pathlib import Path
import re
import sys
import struct
import zipfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from tools.firmware.build_ota_migration import check_slot
from tools.firmware.ota_release import REQUIRED_CHECKS, SPLIT_REQUIRED_CHECKS
from tools.firmware.package_android_update import MAX_ZIP, MAX_IMAGE, signed_metadata
from tools.firmware.package_zigbee_ota import image

ROLES = {'main': 1, 'recovery': 2, 'migration': 3}
FIELDS = {'schemaVersion', 'minAppVersion', 'model', 'layoutVersion', 'identityProtocol',
          'allowedLoaderSha256', 'legacyRecoverySignedHashes', 'targetRecoverySignedHash',
          'allowedSourceSignedHashes', 'main', 'recovery', 'migration', 'qualification', 'zigbeeOta'}


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')


def digest(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('SHA256 must be lowercase hexadecimal')
    return value


def hashes_list(value, *, empty=False):
    if not isinstance(value, list) or not (0 if empty else 1) <= len(value) <= 64 or value != sorted(set(value)):
        raise ValueError('hash allowlist must be sorted, unique and bounded')
    return [digest(entry) for entry in value]


def verify_component(blob, public_key, role):
    parsed = check_slot(blob, 0xb0000 if role == "recovery" else 0xc000, 0x34000 if role == "recovery" else 0xa2000)
    if len(blob) > MAX_IMAGE or parsed['flags'] != 0 or struct.unpack_from('<I', blob, 4)[0] or struct.unpack_from('<I', blob, 28)[0]:
        raise ValueError('only ordinary signed images are accepted')
    if parsed['protected'].get(0xa0) != b'VIMAR30805\x02' or parsed['protected'].get(0xa1) != bytes([ROLES[role]]):
        raise ValueError('authenticated component role/profile mismatch: ' + role)
    if set(parsed['protected']) - {0x50, 0xa0, 0xa1} or (0x50 in parsed['protected'] and len(parsed['protected'][0x50]) != 4):
        raise ValueError('unsupported protected TLV')
    keyhash = hashlib.sha256(public_key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).digest()
    if set(parsed["unprotected"]) != {1, 0x10, 0x22} or parsed["unprotected"].get(1) != keyhash:
        raise ValueError("image key hash or unprotected TLV contract mismatch")
    region_digest = hashlib.sha256(blob[:parsed['authenticated_end']]).digest()
    if parsed['unprotected'].get(0x10) != region_digest or 0x22 not in parsed['unprotected']:
        raise ValueError('missing authenticated digest/signature')
    try:
        public_key.verify(parsed['unprotected'][0x22], region_digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    except (InvalidSignature, ValueError) as error:
        raise ValueError('component signature invalid: ' + role) from error
    return dict(signed_metadata(blob, role + '.signed.bin'), role=role.upper())


def verify_zigbee_carrier(ota, main, public_key, main_metadata):
    """Authenticate the exact compressed carrier and independently decode MAIN.

    Only the fixed 66-byte SDK envelope and existing profile2 ARMThumb/LZMA2
    parameters are supported. No URL or per-device identity enters the ZIP.
    """
    if not 66 + 512 <= len(ota) <= 66 + 0xa2000:
        raise ValueError('Zigbee carrier size outside staging contract')
    magic, version, header_size, control, manufacturer, kind, file_version, stack = struct.unpack_from('<IHHHHHIH', ota)
    total, minimum, maximum, tag, compressed_size = struct.unpack_from('<IHHHI', ota, 52)
    numbers = image(main)['version'].replace('+', '.').split('.')
    numbers = list(map(int, numbers)) + [0] * (4 - len(numbers))
    expected_version = (numbers[0] << 24) | (numbers[1] << 16) | (numbers[2] << 8) | numbers[3]
    if any(value > 255 for value in numbers) or numbers[3] != 0 or (magic, version, header_size, control, manufacturer, kind, stack,
            minimum, maximum, tag, total, compressed_size, file_version) != (
            0x0beef11e, 0x100, 60, 4, 0xfff1, 0x3085, 2, 1, 1, 0, len(ota), len(ota)-66, expected_version):
        raise ValueError('Zigbee envelope/model/version mismatch')
    compressed = ota[66:]; parsed = image(compressed); ordinary = image(main)
    protected = parsed['protected']; unprotected = parsed['unprotected']
    expected_tags = {0x70, 0x71, 0x72, 0xa0, 0xa1} | ({0x50} if 0x50 in ordinary['protected'] else set())
    if (parsed['header'] != 512 or parsed['flags'] != 0xc00 or set(protected) != expected_tags or
            protected[0xa0] != b'VIMAR30805\x02' or protected[0xa1] != b'\x01' or
            protected.get(0x50) != ordinary['protected'].get(0x50) or
            protected[0x70] != struct.pack('<I', ordinary['size']) or
            protected[0x71] != bytes.fromhex(main_metadata['signedRegionSha256'])):
        raise ValueError('Compressed MAIN role/profile/decompression binding mismatch')
    keyhash = hashlib.sha256(public_key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).digest()
    if set(unprotected) != {1, 0x10, 0x22} or unprotected[1] != keyhash:
        raise ValueError('Compressed MAIN key/TLV contract mismatch')
    region_digest = hashlib.sha256(compressed[:parsed['authenticated_end']]).digest()
    if unprotected[0x10] != region_digest:
        raise ValueError('Compressed MAIN digest mismatch')
    try:
        public_key.verify(unprotected[0x22], region_digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        public_key.verify(protected[0x72], protected[0x71], ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    except (ValueError, InvalidSignature) as error:
        raise ValueError('Compressed or reconstructed MAIN signature invalid') from error
    # Normalise compression-only header fields, preserving all other ordinary
    # header bytes and flags; a matching payload alone is insufficient.
    normal = bytearray(compressed[:512])
    struct.pack_into('<H', normal, 10, struct.unpack_from('<H', main, 10)[0])
    struct.pack_into('<II', normal, 12, ordinary['size'], 0)
    if bytes(normal) != main[:512]:
        raise ValueError('Compressed MAIN ordinary header mismatch')
    stream = compressed[512:512+parsed['size']]
    if stream[:2] != b'\x06\x5d':
        raise ValueError('Unsupported SDK compression parameters')
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[
        {'id': lzma.FILTER_ARMTHUMB}, {'id': lzma.FILTER_LZMA2, 'dict_size': 32768}])
    try:
        decoded = decoder.decompress(stream[2:], max_length=ordinary['size']+1)
    except lzma.LZMAError as error:
        raise ValueError('Invalid compressed MAIN stream') from error
    if not decoder.eof or decoder.unused_data or decoded != main[512:512+ordinary['size']]:
        raise ValueError('Compressed carrier does not reconstruct exact signed MAIN payload')
    return dict(file='main.ota', size=len(ota), fileSha256=sha(ota), manufacturerCode=0xfff1,
                imageType=0x3085, fileVersion=file_version, model='VIMAR30805', profile=2,
                mainSignedRegionSha256=main_metadata['signedRegionSha256'])


def create_common_update_bundle(release, output, private_key, public_key):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to(ROOT / 'inputs'):
        raise ValueError('output must be new and outside immutable inputs')
    release = Path(release).resolve()
    raw = release.read_bytes(); descriptor = json.loads(raw)
    if not isinstance(descriptor, dict) or set(descriptor) - FIELDS or not (FIELDS - {'recovery', 'migration', 'zigbeeOta'}) <= set(descriptor):
        raise ValueError('unknown or missing common release field')
    if (type(descriptor['schemaVersion']) is not int or descriptor['schemaVersion'] != 2 or descriptor['model'] != 'VIMAR30805'
            or type(descriptor['layoutVersion']) is not int or descriptor['layoutVersion'] != 2
            or type(descriptor['identityProtocol']) is not int or descriptor['identityProtocol'] != 1):
        raise ValueError('unsupported common release contract')
    if not isinstance(descriptor['minAppVersion'], str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', descriptor['minAppVersion']):
        raise ValueError('invalid minimum app version')
    for field in ('allowedLoaderSha256', 'allowedSourceSignedHashes', 'legacyRecoverySignedHashes'):
        hashes_list(descriptor[field], empty=field == 'legacyRecoverySignedHashes')
    digest(descriptor['targetRecoverySignedHash'])
    if bool(descriptor['legacyRecoverySignedHashes']) != ('migration' in descriptor):
        raise ValueError('migration and its explicit legacy recovery allowlist must occur together')
    sources = {'release': dict(path=str(release), sha256=sha(raw))}

    def source(field):
        record = descriptor[field]
        if not isinstance(record, dict) or set(record) != {'path', 'sha256'} or not isinstance(record['path'], str):
            raise ValueError('invalid source: ' + field)
        path = (release.parent / record['path']).resolve(); blob = path.read_bytes()
        if sha(blob) != digest(record['sha256']):
            raise ValueError('source hash mismatch: ' + field)
        sources[field] = dict(path=str(path), sha256=sha(blob))
        return blob

    public = serialization.load_pem_public_key(Path(public_key).read_bytes())
    private = serialization.load_pem_private_key(Path(private_key).read_bytes(), password=None)
    if not isinstance(public, ec.EllipticCurvePublicKey) or not isinstance(public.curve, ec.SECP256R1) or not isinstance(private, ec.EllipticCurvePrivateKey) or not isinstance(private.curve, ec.SECP256R1):
        raise ValueError('ECDSA P256 keys required')
    if private.public_key().public_numbers() != public.public_numbers():
        raise ValueError('signing key pair mismatch')
    components = {role: source(role) for role in ROLES if role in descriptor}
    metadata = {role: verify_component(blob, public, role) for role, blob in components.items()}
    carrier = source('zigbeeOta') if 'zigbeeOta' in descriptor else None
    ota_metadata = verify_zigbee_carrier(carrier, components['main'], public, metadata['main']) if carrier is not None else None
    if 'recovery' in metadata and metadata['recovery']['signedRegionSha256'] != descriptor['targetRecoverySignedHash']:
        raise ValueError('target recovery digest mismatch')
    qraw = source('qualification'); qualification = json.loads(qraw)
    if not isinstance(qualification, dict) or qualification.get('schemaVersion') != 2 or qualification.get('model') != 'VIMAR30805' or qualification.get('layoutVersion') != 2:
        raise ValueError('unsupported qualification')
    if any(qualification.get(field) is not True for field in (*REQUIRED_CHECKS, *SPLIT_REQUIRED_CHECKS)):
        raise ValueError('incomplete hardware qualification')
    qualified_components = {role: sha(blob) for role, blob in components.items()}
    if carrier is not None:
        qualified_components['zigbeeOta'] = sha(carrier)
    if qualification.get('allowedLoaderSha256') != descriptor['allowedLoaderSha256'] or qualification.get('components') != qualified_components:
        raise ValueError('qualification not bound to components/loader allowlist')
    manifest = {field: value for field, value in descriptor.items() if field not in {*ROLES, 'qualification', 'zigbeeOta'}}
    manifest.update(metadata); manifest['qualificationSha256'] = sha(qraw)
    if ota_metadata is not None:
        manifest['zigbeeOta'] = ota_metadata
    manifest['bundleId'] = sha(canonical(manifest)); manifest_raw = canonical(manifest)
    signature = private.sign(manifest_raw, ec.ECDSA(hashes.SHA256()))
    public.verify(signature, manifest_raw, ec.ECDSA(hashes.SHA256()))
    entries = {'manifest.json': manifest_raw, 'manifest.sig': signature,
               **{role + '.signed.bin': blob for role, blob in components.items()}}
    if carrier is not None:
        entries['main.ota'] = carrier
    if len(manifest_raw) > 65536 or len(signature) > 80 or sum(map(len, entries.values())) > MAX_ZIP:
        raise ValueError('common release exceeds import limits')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name, blob in entries.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)); info.external_attr = 0o100644 << 16
            archive.writestr(info, blob)
    result = buffer.getvalue()
    if len(result) > MAX_ZIP:
        raise ValueError('ZIP exceeds import limit')
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open('xb') as destination:
            destination.write(result)
    except FileExistsError as error:
        raise ValueError('output must not overwrite an existing package') from error
    return dict(path=str(output), sha256=sha(result), bundleId=manifest['bundleId'], sources=sources,
                transformations=['common signed components copied verbatim; authenticated role/profile/signature verified',
                                 'qualified component hashes and finite loader allowlist bound into canonical signed schema2 manifest'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('release', 'output', 'private-key', 'public-key'):
        parser.add_argument('--' + name, type=Path, required=True)
    print(json.dumps(create_common_update_bundle(**vars(parser.parse_args())), indent=2))


if __name__ == '__main__':
    main()
