#!/usr/bin/env python3
"""Create a qualified, device-bound Android BLE update ZIP; no hardware IO.

See apps/android-updater/test-fixtures/README.md for the frozen schema1 contract.
All source paths are explicit, relative to their containing JSON descriptor.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from tools.firmware import ota_release as release_gate
from tools.firmware.build_ota_migration import validate_manifest, uid_words, check_slot, digest
from tools.firmware.package_zigbee_ota import image, run_imgtool
from tools.firmware.toolchain_paths import toolchain_paths

MAX_ZIP = 2 * 1024 * 1024
MAX_IMAGE = 0xa4000


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_source(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return path, json.loads(raw), dict(path=str(path), sha256=sha(raw))


def signed_metadata(blob, filename, *, historical=False):
    parsed = image(blob)
    # New components use ordinary triples; frozen migration retains its wire label.
    major, minor, revision, build = map(int, re.split('[.+]', parsed['version']))
    if not historical and build != 0:
        raise ValueError('new main must use SemVer without a historical build counter')
    return dict(file=filename, size=len(blob),
                version=parsed['version'] if historical else f'{major}.{minor}.{revision}',
                wireVersion=[major, minor, revision, build], fileSha256=sha(blob),
                signedRegionSha256=sha(blob[:parsed['authenticated_end']]))


def create_update_bundle(device, ota_release, migration_input, migration_report, output):
    output = Path(output).absolute()
    if output.resolve().is_relative_to(ROOT / 'inputs') or output.exists() or output.is_symlink():
        raise ValueError('output must be new and outside immutable inputs')
    device_path, descriptor, device_source = json_source(device)
    if type(descriptor.get('schemaVersion')) is not int or descriptor['schemaVersion'] != 1:
        raise ValueError('unsupported device descriptor schema')
    name = descriptor.get('name')
    ieee, address = descriptor.get('ieee'), descriptor.get('bleAddress')
    if not isinstance(name, str) or not 1 <= len(name) <= 128:
        raise ValueError('invalid device name')
    if not isinstance(ieee, str) or not re.fullmatch('[0-9a-fA-F]{16}', ieee):
        raise ValueError('IEEE must be sixteen hexadecimal digits')
    if not isinstance(address, str) or not re.fullmatch('(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', address):
        raise ValueError('explicit BLE address required')
    uid = uid_words(descriptor.get('uid'))
    pair = release_gate.load_ota_pair(ota_release)
    validated = validate_manifest(migration_input, pair['recovery']['path'])
    if uid != validated['uid'] or pair.get('ota_profile', 1) != validated['ota_profile']:
        raise ValueError('device UID or OTA pair/profile mismatch')
    if validated['ota_profile'] == 2:
        qualified_binding = json.loads(pair['pair_bindings_data'])
        if validated['loader_sha256'] not in qualified_binding.get('allowed_loaders', []):
            raise ValueError('qualified release does not authorize the actual loader')
        if validated['sources']['pair_bindings']['sha256'] != pair['pair_bindings']['sha256']:
            raise ValueError('qualified release and migration pair binding mismatch')
    report_path, report, report_source = json_source(migration_report)
    for field in ('uid', 'ota_profile', 'loader_sha256', 'stock_restore_digest', 'recovery_sha256', 'recovery_version'):
        if report.get(field) != validated[field]:
            raise ValueError('migration report binding mismatch: ' + field)
    for field, source in validated['sources'].items():
        if report.get('sources', {}).get(field, {}).get('sha256') != source['sha256']:
            raise ValueError('migration report source mismatch: ' + field)
    if report.get('schema_version') != 1 or report.get('status') != 'signed ordinary bootstrap verified; hardware qualification pending':
        raise ValueError('migration report does not describe a completed verified build')
    # The frozen artifact is selected by its build report, never by mtime/glob.
    artifacts = report.get('artifacts', {})
    names = [n for n in artifacts if n.endswith('.signed.bin')]
    if len(names) != 1 or Path(names[0]).name != names[0]:
        raise ValueError('migration report must select exactly one signed BIN')
    migration_path = report_path.parent / names[0]
    migration_blob = migration_path.read_bytes()
    artifact = artifacts[names[0]]
    if artifact.get('sha256') != sha(migration_blob) or artifact.get('size') != len(migration_blob):
        raise ValueError('migration artifact SHA256/size mismatch')
    check_slot(migration_blob, 0xc000, MAX_IMAGE, report.get('migration_version'))
    if report.get('migration_version') != ('0.8.1+0' if validated['ota_profile'] == 2 else '0.8.0+0'):
        raise ValueError('unsupported frozen migration version')
    paths = toolchain_paths()
    sources = dict(device=device_source, ota_release=dict(path=pair['manifest_path'], sha256=pair['manifest_sha256']),
                   qualification=pair['qualification'], migration_input=validated['sources']['input_manifest'],
                   migration_report=report_source, migration=dict(path=str(migration_path), sha256=sha(migration_blob)))
    commands = []

    def descriptor_image(record, role, base, capacity):
        if not isinstance(record, dict) or not isinstance(record.get('path'), str):
            raise ValueError('missing device image reference: ' + role)
        path = (device_path.parent / record['path']).resolve()
        blob = path.read_bytes()
        if sha(blob) != digest(record.get('sha256'), role):
            raise ValueError('device image SHA256 mismatch: ' + role)
        check_slot(blob, base, capacity)
        sources[role] = dict(path=str(path), sha256=sha(blob))
        return blob

    old = descriptor_image(descriptor.get('oldRecovery'), 'old_recovery', 0xb0000, 0x40000)
    initial_records = descriptor.get('initialMain')
    if not isinstance(initial_records, list) or not 1 <= len(initial_records) <= 64:
        raise ValueError('explicit nonempty initial main allowlist required')
    initial = [descriptor_image(record, 'initial_main_' + str(i), 0xc000, MAX_IMAGE) for i, record in enumerate(initial_records)]
    # Verify immutable snapshots, rather than paths that can change after hashing.
    with tempfile.TemporaryDirectory(prefix='android-bundle-verify-') as temporary:
        for i, blob in enumerate([migration_blob, old, *initial]):
            path = Path(temporary) / (str(i) + '.bin')
            path.write_bytes(blob)
            run_imgtool(['verify', '-k', paths['public_key'], path], commands)
    migration_metadata = signed_metadata(migration_blob, 'migration.signed.bin', historical=True)
    main_metadata = signed_metadata(pair['main']['data'], 'main.signed.bin')
    manifest = dict(schemaVersion=1, minAppVersion='0.1.0',
                    device=dict(name=name, ieee=ieee.lower(), uid=[f'{x:08x}' for x in uid], bleAddress=address.upper()),
                    legacyRecoverySignedHash=signed_metadata(old, '', historical=True)['signedRegionSha256'],
                    targetRecoverySignedHash=signed_metadata(pair['recovery']['data'], '', historical=True)['signedRegionSha256'],
                    allowedSourceSignedHashes=sorted({signed_metadata(blob, '', historical=True)['signedRegionSha256'] for blob in initial}),
                    migration=migration_metadata, main=main_metadata,
                    provenance=dict(deviceDescriptorSha256=device_source['sha256'], otaReleaseSha256=pair['manifest_sha256'],
                                    qualificationSha256=pair['qualification']['sha256'],
                                    migrationInputSha256=validated['sources']['input_manifest']['sha256'],
                                    migrationReportSha256=report_source['sha256']))
    canonical = lambda value: (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')
    manifest['bundleId'] = sha(canonical(manifest))
    raw = canonical(manifest)
    private_key = serialization.load_pem_private_key(paths['private_key'].read_bytes(), password=None)
    public_key = serialization.load_pem_public_key(paths['public_key'].read_bytes())
    if not isinstance(private_key, ec.EllipticCurvePrivateKey) or not isinstance(private_key.curve, ec.SECP256R1):
        raise ValueError('firmware signing key must be ECDSA P-256')
    signature = private_key.sign(raw, ec.ECDSA(hashes.SHA256()))
    public_key.verify(signature, raw, ec.ECDSA(hashes.SHA256()))
    entries = {'manifest.json': raw, 'manifest.sig': signature,
               'migration.signed.bin': migration_blob, 'main.signed.bin': pair['main']['data']}
    if len(raw) > 65536 or len(signature) > 80 or sum(map(len, entries.values())) > MAX_ZIP:
        raise ValueError('bundle exceeds import limits')
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as zipped:
        for filename, blob in entries.items():
            entry = zipfile.ZipInfo(filename, date_time=(1980, 1, 1, 0, 0, 0))
            entry.external_attr = 0o100644 << 16
            zipped.writestr(entry, blob)
    result = archive.getvalue()
    if len(result) > MAX_ZIP:
        raise ValueError('ZIP exceeds import limit')
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents races from replacing an existing package.
    try:
        with output.open('xb') as destination:
            destination.write(result)
    except FileExistsError as error:
        raise ValueError('output must not overwrite an existing package') from error
    return dict(path=str(output), sha256=sha(result), bundleId=manifest['bundleId'], sources=sources,
                transformations=['signed images copied verbatim', 'SHA256 over MCUboot header/payload/protected TLVs separately from complete file',
                                 'canonical ASCII JSON signed ECDSA-P256/SHA256 DER; fixed ZIP names/order/timestamps/mode'], commands=commands)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('device', 'ota-release', 'migration-input', 'migration-report', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    print(json.dumps(create_update_bundle(**vars(parser.parse_args())), indent=2))


if __name__ == '__main__':
    main()
