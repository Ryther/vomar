"""Independent synthetic Android backup exports; no target, keys or vendor bytes."""
import copy
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import zipfile

import pytest

from tools.firmware import verify_android_backup as verifier


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_zip(path, entries, *, mode=0o100600):
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            info = zipfile.ZipInfo(name)
            info.external_attr = mode << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
    return path


@pytest.fixture
def exported(tmp_path):
    flash = bytearray(b'\x5a' * 1048576)
    struct.pack_into('<II', flash, 0, 0x20040000, 0x101)
    ficr = bytearray(b'\xff' * 4096)
    for offset, value in {0x10: 4096, 0x14: 256, 0x60: 0x12345678, 0x64: 0xffffffff,
                          0x100: 0x52840, 0x10c: 256, 0x110: 1024}.items():
        struct.pack_into('<I', ficr, offset, value)
    regions = {'flash.bin': bytes(flash), 'ficr.bin': bytes(ficr), 'uicr.bin': b'\xff' * 4096}
    manifest = {
        'schema': 1, 'type': 'nrf52840-read-only-double-backup',
        'target': {'chip': 'nRF52840', 'part': '0x00052840', 'uid': ['0x12345678', '0xffffffff'],
                   'identitySource': 'live FICR before/after both passes', 'commercialModelVerified': False,
                   'model': 'unknown nRF52840 device'},
        'byteExactDoubleRead': True, 'startedAt': '2026-10-23T12:00:00Z',
        'verifiedAt': '2026-10-23T12:10:00.000000001Z', 'snapshotAtomic': False,
        'protocol': {'id': 'jlink-raw-swd-ap0-read-v1', 'swdClockKhz': 100, 'maxBlockBytes': 512,
                     'tarBoundaryBytes': 1024, 'independentBlockSentinels': True},
        'scope': {'haltAttempted': False, 'resetAttempted': False, 'eraseAttempted': False,
                  'memoryWrite': False, 'flashed': False, 'targetSupplyChanged': False,
                  'debugPortConfigured': True, 'restorationVerified': False},
        'provenance': {'appVersion': '0.3.2', 'probeFirmware': 'Synthetic J-Link', 'usbVendorId': 0x1366,
                       'usbProductId': 0x1060, 'interfaceId': 4, 'inputEndpoint': 0x85,
                       'outputEndpoint': 3, 'targetMillivolts': 3300},
        'regions': [{'file': name, 'start': f'0x{start:08x}', 'size': len(regions[name]),
                     'sha256': sha(regions[name]), 'verifiedCopies': 2}
                    for name, start in [('flash.bin', 0), ('ficr.bin', 0x10000000), ('uicr.bin', 0x10001000)]]}
    def emit(manifest_override=None, regions_override=None, extras=()):
        m = manifest if manifest_override is None else manifest_override
        blobs = regions if regions_override is None else regions_override
        entries = list(blobs.items()) + [('manifest.json', json.dumps(m).encode()), ('README.txt', b'Synthetic private backup documentation.\n')]
        return write_zip(tmp_path / 'backup.zip', entries + list(extras))
    return manifest, regions, emit


def test_valid_export_verifies_bytes_but_does_not_prove_double_acquisition_or_restoration(exported):
    _, regions, emit = exported
    path = emit(); original = path.read_bytes()
    result = verifier.verify_backup(path)
    assert result['verified'] is True
    assert result['uid'] == ['12345678', 'ffffffff']
    assert result['regions']['flash.bin']['sha256'] == sha(regions['flash.bin'])
    assert result['recognizedApplications'] == []
    assert result['commercialModelVerified'] is False
    assert result['producerReported']['byteExactDoubleRead'] is True
    assert result['doubleAcquisitionIndependentlyProven'] is False
    assert result['restorationQualified'] is False
    assert path.read_bytes() == original


@pytest.mark.parametrize('damage', ['unknown-field', 'unknown-target-field', 'schema-bool', 'atomic', 'write',
    'double-read', 'verified-copies', 'protocol-bool', 'region-order', 'region-address', 'missing-region',
    'region-hash', 'duplicate-region', 'uid-case', 'wrong-uid', 'model-claim', 'unproven-recognition',
    'unknown-provenance', 'voltage', 'usb', 'timestamp', 'backwards-nanoseconds'])
def test_rejects_invalid_or_exaggerated_current_manifest(exported, damage):
    manifest, _, emit = exported
    m = copy.deepcopy(manifest)
    if damage == 'unknown-field': m['identityFile'] = 'not allowed'
    if damage == 'unknown-target-field': m['target']['name'] = 'not part of archive contract'
    if damage == 'schema-bool': m['schema'] = True
    if damage == 'atomic': m['snapshotAtomic'] = True
    if damage == 'write': m['scope']['memoryWrite'] = True
    if damage == 'double-read': m['byteExactDoubleRead'] = False
    if damage == 'verified-copies': m['regions'][0]['verifiedCopies'] = True
    if damage == 'protocol-bool': m['protocol']['swdClockKhz'] = True
    if damage == 'region-order': m['regions'].reverse()
    if damage == 'region-address': m['regions'][0]['start'] = '0x00001000'
    if damage == 'missing-region': m['regions'].pop()
    if damage == 'region-hash': m['regions'][0]['sha256'] = '0' * 64
    if damage == 'duplicate-region': m['regions'][1] = m['regions'][0]
    if damage == 'uid-case': m['target']['uid'][0] = '0X12345678'
    if damage == 'wrong-uid': m['target']['uid'][0] = '0x12345679'
    if damage == 'model-claim': m['target']['commercialModelVerified'] = True
    if damage == 'unproven-recognition':
        m['target'].update(applicationDigestMatched=True, firmwareModel='VIMAR30805', recognizedApplications=[])
    if damage == 'unknown-provenance': m['provenance']['privateKey'] = 'not accepted'
    if damage == 'voltage': m['provenance']['targetMillivolts'] = 0
    if damage == 'usb': m['provenance']['usbVendorId'] = 0
    if damage == 'timestamp': m['verifiedAt'] = 'yesterday'
    if damage == 'backwards-nanoseconds':
        m['startedAt'] = '2026-10-23T12:00:00.000000002Z'; m['verifiedAt'] = '2026-10-23T12:00:00.000000001Z'
    with pytest.raises(ValueError): verifier.verify_backup(emit(m))


@pytest.mark.parametrize('region,offset,value', [('ficr.bin', 0x60, 0), ('ficr.bin', 0x100, 0x52832),
    ('ficr.bin', 0x10, 1024), ('ficr.bin', 0x14, 512), ('ficr.bin', 0x10c, 128), ('ficr.bin', 0x110, 512),
    ('flash.bin', 0, 0x20000000), ('flash.bin', 0, 0x20040008), ('flash.bin', 4, 0x100), ('flash.bin', 4, 0x100001)])
def test_matching_updated_hash_does_not_hide_wrong_geometry_identity_or_vectors(exported, region, offset, value):
    manifest, regions, emit = exported
    m = copy.deepcopy(manifest); blobs = dict(regions)
    changed = bytearray(blobs[region]); struct.pack_into('<I', changed, offset, value); blobs[region] = bytes(changed)
    next(row for row in m['regions'] if row['file'] == region)['sha256'] = sha(blobs[region])
    with pytest.raises(ValueError): verifier.verify_backup(emit(m, blobs))


@pytest.mark.parametrize('damage', ['extra', 'duplicate', 'traversal', 'symlink', 'directory', 'encrypted', 'expanded', 'compressed', 'json-duplicate', 'json-nested-duplicate', 'json-nan', 'truncated', 'prefix', 'trailing', 'comment', 'crc'])
def test_rejects_unsafe_archive_and_non_strict_json(exported, tmp_path, damage):
    manifest, regions, emit = exported
    path = emit()
    if damage in ('extra', 'duplicate', 'traversal'):
        name = {'extra': 'extra.txt', 'duplicate': 'flash.bin', 'traversal': '../flash.bin'}[damage]
        with pytest.warns(UserWarning) if damage == 'duplicate' else nullcontext(): path = emit(extras=[(name, b'bad')])
    elif damage in ('symlink', 'directory'):
        entries = list(regions.items()) + [('manifest.json', json.dumps(manifest).encode()), ('README.txt', b'test')]
        path = write_zip(path, entries, mode=0o120777 if damage == 'symlink' else 0o040700)
    elif damage == 'encrypted':
        data = bytearray(path.read_bytes())
        for signature, flags in [(b'PK\x03\x04', 6), (b'PK\x01\x02', 8)]:
            pos = 0
            while (pos := data.find(signature, pos)) >= 0:
                data[pos + flags] |= 1; pos += 4
        path.write_bytes(data)
    elif damage == 'expanded':
        blobs = dict(regions); blobs['flash.bin'] = bytes(8 * 1024 * 1024); path = emit(regions_override=blobs)
    elif damage == 'compressed':
        path.write_bytes(path.read_bytes() + bytes(2 * 1024 * 1024))
    elif damage == 'prefix': path.write_bytes(b'not the producer' + path.read_bytes())
    elif damage == 'trailing': path.write_bytes(path.read_bytes() + b'not the producer')
    elif damage == 'comment':
        with zipfile.ZipFile(path, 'a') as archive: archive.comment = b'not emitted by Android'
    elif damage == 'crc':
        data = bytearray(path.read_bytes()); data[data.index(b'PK\x01\x02') + 16] ^= 1; path.write_bytes(data)
    elif damage.startswith('json-'):
        encoded = json.dumps(manifest)
        if damage == 'json-duplicate': encoded = encoded[:-1] + ',"schema":1}'
        if damage == 'json-nested-duplicate': encoded = encoded.replace('"part": "0x00052840"', '"part":"0x00052840","part":"0x00052840"')
        if damage == 'json-nan': encoded = encoded.replace('"targetMillivolts": 3300', '"targetMillivolts": NaN')
        path = write_zip(path, list(regions.items()) + [('manifest.json', encoded.encode()), ('README.txt', b'test')])
    else: path.write_bytes(path.read_bytes()[:-12])
    with pytest.raises(ValueError): verifier.verify_backup(path)


def test_prior_archive_compares_only_three_dump_bytes_and_refuses_mismatch(exported, tmp_path):
    _, regions, emit = exported
    path = emit(); prior = tmp_path / 'prior.zip'
    entries = [('stock-' + name, blob) for name, blob in regions.items()] + [('signing-public.pem', b'not parsed as a trust anchor')]
    write_zip(prior, entries); before = prior.read_bytes()
    result = verifier.verify_backup(path, compare_stock_recovery=prior)
    assert result['comparison']['allThreeRegionsByteIdentical'] is True
    assert result['comparison']['restorationPackageVerified'] is False
    assert prior.read_bytes() == before
    entries[0] = ('stock-flash.bin', bytes(1048576)); write_zip(prior, entries)
    with pytest.raises(ValueError, match='(?i)prior.*flash|flash.*prior'): verifier.verify_backup(path, compare_stock_recovery=prior)


def test_recognition_is_recomputed_from_bytes_not_trusted_manifest_fields(exported, monkeypatch):
    manifest, regions, emit = exported
    # Synthetic fingerprint only. No proprietary firmware is embedded in tests.
    fingerprint = dict(id='synthetic-public-test', model='TESTMODEL', radio='test', offset=0x26000,
                       size=64, sha256=sha(regions['flash.bin'][0x26000:0x26040]))
    monkeypatch.setattr(verifier, 'STOCK_APPLICATIONS', (fingerprint,))
    m = copy.deepcopy(manifest)
    m['target'].update(model='stock application recognized; hardware model unverified',
                       applicationDigestMatched=True, firmwareModel='TESTMODEL', recognizedApplications=[fingerprint])
    result = verifier.verify_backup(emit(m))
    assert result['recognizedApplications'] == [fingerprint]
    assert result['commercialModelVerified'] is False
    forged = copy.deepcopy(m)
    forged['target']['recognizedApplications'][0]['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='recognition'): verifier.verify_backup(emit(forged))


def test_prior_comparison_does_not_open_non_dump_members(exported, tmp_path, monkeypatch):
    _, regions, emit = exported
    prior = write_zip(tmp_path / 'prior.zip', [('stock-' + name, blob) for name, blob in regions.items()]
                      + [('restorer.signed.bin', b'not opened'), ('signing-public.pem', b'not opened')])
    original_open = zipfile.ZipFile.open
    def guarded_open(archive, member, *args, **kwargs):
        name = member.filename if isinstance(member, zipfile.ZipInfo) else member
        assert name not in ('restorer.signed.bin', 'signing-public.pem')
        return original_open(archive, member, *args, **kwargs)
    monkeypatch.setattr(zipfile.ZipFile, 'open', guarded_open)
    assert verifier.verify_backup(emit(), compare_stock_recovery=prior)['comparison']['allThreeRegionsByteIdentical']


def test_cli_is_read_only_and_returns_nonzero_for_invalid_export(exported):
    _, _, emit = exported
    path = emit(); before = path.read_bytes()
    command = [sys.executable, str(Path(verifier.__file__)), '--backup', str(path)]
    result = subprocess.run(command, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['verified'] is True
    assert path.read_bytes() == before
    path.write_bytes(b'not a ZIP')
    failed = subprocess.run(command, text=True, capture_output=True)
    assert failed.returncode != 0
    assert 'Traceback' not in failed.stderr
