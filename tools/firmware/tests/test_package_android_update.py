"""Synthetic signed Android update packages: no device access or stock artifacts."""
from local_inputs import local_input
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import zipfile

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from tools.firmware import build_ota_migration, ota_release, package_zigbee_ota

ROOT = Path(__file__).resolve().parents[3]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value))
    return path


@pytest.fixture
def sources(tmp_path, monkeypatch):
    local_input(package_zigbee_ota.IMGTOOL)
    local_input(package_zigbee_ota.PYTHON)
    key = ec.generate_private_key(ec.SECP256R1())
    private = tmp_path / 'private.pem'
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public = tmp_path / 'public.pem'
    public.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    monkeypatch.setenv('VIMAR_SIGNING_PRIVATE_KEY', str(private))
    monkeypatch.setenv('VIMAR_SIGNING_PUBLIC_KEY', str(public))
    for module in (build_ota_migration, ota_release, package_zigbee_ota):
        monkeypatch.setattr(module, 'PUBLIC_KEY', public)

    def signed(name, version, base):
        raw = tmp_path / (name + '.raw')
        raw.write_bytes(bytes(512) + struct.pack('<II', 0x20010000, base + 513) + bytes(1016))
        out = tmp_path / (name + '.signed.bin')
        subprocess.run([str(package_zigbee_ota.PYTHON), str(package_zigbee_ota.IMGTOOL), 'sign', '--header-size', '512', '--slot-size', '0xa4000', '--align', '4', '--version', version, '--overwrite-only', '-k', str(private), str(raw), str(out)], check=True, capture_output=True)
        return out

    def record(path, version=None):
        return dict(path=path.name, sha256=sha(path.read_bytes()), **({'version': version} if version else {}))

    main = signed('main', '0.5.8+0', 0xc000)
    initial = signed('initial', '0.5.3+0', 0xc000)
    recovery = signed('recovery', '0.7.1+0', 0xb0000)
    old = signed('old', '0.7.0+0', 0xb0000)
    migration = signed('migration', '0.8.0+0', 0xc000)
    evidence = write_json(tmp_path / 'qualification.json', dict(schema_version=1, main_sha256=sha(main.read_bytes()), recovery_sha256=sha(recovery.read_bytes()), **{k: True for k in ota_release.REQUIRED_CHECKS}))
    pair = write_json(tmp_path / 'pair.json', dict(schema_version=1, main=record(main, '0.5.8+0'), recovery=record(recovery, '0.7.1+0'), qualification=record(evidence)))
    (tmp_path / 'loader.hex').write_text(':0400000001020304F2\n:00000001FF\n')
    loader = tmp_path / 'loader.bin'
    loader.write_bytes(bytes([1, 2, 3, 4]) + b'\xff' * (0xc000 - 4))
    (tmp_path / 'restorer.signed.bin').write_bytes(recovery.read_bytes())
    authorization = write_json(tmp_path / 'restore.json', dict(deviceid=['11223344', '55667788'], artifacts={n: dict(size=(tmp_path / n).stat().st_size, sha256=sha((tmp_path / n).read_bytes())) for n in ('loader.hex', 'restorer.signed.bin')}))
    input_path = write_json(tmp_path / 'input.json', dict(schema_version=1, uid=['11223344', '55667788'], loader_path=loader.name, loader_sha256=sha(loader.read_bytes()), restore_manifest_path=authorization.name, restore_manifest_sha256=sha(authorization.read_bytes()), stock_restore_digest=sha(recovery.read_bytes()), recovery_sha256=sha(recovery.read_bytes()), recovery_version='0.7.1+0'))
    validated = build_ota_migration.validate_manifest(input_path, recovery)
    validated.pop('recovery_bytes')
    report = write_json(tmp_path / 'artifact-manifest.json', dict(validated, schema_version=1, migration_version='0.8.0+0', status='signed ordinary bootstrap verified; hardware qualification pending', artifacts={migration.name: dict(size=migration.stat().st_size, sha256=sha(migration.read_bytes()))}))
    device = write_json(tmp_path / 'device.json', dict(schemaVersion=1, name='Synthetic dimmer', ieee='0011223344556677', uid=['11223344', '55667788'], bleAddress='C0:00:00:00:00:01', oldRecovery=record(old), initialMain=[record(initial)]))
    return dict(device=device, ota_release=pair, migration_input=input_path, migration_report=report, output=tmp_path / 'device.zip'), key


def package(args):
    from tools.firmware.package_android_update import create_update_bundle
    return create_update_bundle(**args)


def test_signed_four_entry_bundle(sources):
    args, key = sources
    result = package(args)
    with zipfile.ZipFile(args['output']) as archive:
        assert archive.namelist() == ['manifest.json', 'manifest.sig', 'migration.signed.bin', 'main.signed.bin']
        raw = archive.read('manifest.json')
        key.public_key().verify(archive.read('manifest.sig'), raw, ec.ECDSA(hashes.SHA256()))
        m = json.loads(raw)
        assert m['device']['uid'] == ['11223344', '55667788']
        assert m['main']['version'] == '0.5.8'
        assert m['main']['wireVersion'] == [0, 5, 8, 0]
        assert m['migration']['version'] == '0.8.0+0'
        for role in ('main', 'migration'):
            blob = archive.read(m[role]['file'])
            parsed = package_zigbee_ota.image(blob)
            assert m[role]['fileSha256'] == sha(blob)
            assert m[role]['signedRegionSha256'] == sha(blob[:parsed['authenticated_end']])
            assert m[role]['signedRegionSha256'] != m[role]['fileSha256']
        assert b'PRIVATE KEY' not in b''.join(archive.read(n) for n in archive.namelist())
    assert result['sha256'] == sha(args['output'].read_bytes())
    assert result['sources'] and result['transformations']


def test_triple_pair_manifest_builds_real_signed_android_bundle(sources):
    args, key = sources
    pair = json.loads(args['ota_release'].read_text())
    pair['main']['version'] = '0.5.8'
    pair['recovery']['version'] = '0.7.1'
    write_json(args['ota_release'], pair)
    package(args)
    with zipfile.ZipFile(args['output']) as archive:
        raw = archive.read('manifest.json')
        key.public_key().verify(archive.read('manifest.sig'), raw, ec.ECDSA(hashes.SHA256()))
        metadata = json.loads(raw)['main']
        assert metadata['version'] == '0.5.8'
        assert metadata['wireVersion'] == [0, 5, 8, 0]


@pytest.mark.parametrize('damage', ['uid', 'pair', 'recovery', 'qualification-false', 'qualification-missing', 'report', 'report-uid', 'report-input', 'signature'])
def test_invalid_inputs_produce_no_zip(sources, damage):
    args, _ = sources
    path = args['device']
    d = json.loads(path.read_text())
    if damage == 'uid': d['uid'][0] = '00000000'
    if damage == 'recovery': d['oldRecovery']['sha256'] = '0' * 64
    if damage in ('uid', 'recovery'): write_json(path, d)
    if damage.startswith('qualification'):
        pair = json.loads(args['ota_release'].read_text())
        qpath = path.parent / 'qualification.json'
        q = json.loads(qpath.read_text())
        if damage.endswith('false'): q['power_cut_recovery_verified'] = False
        else: del q['power_cut_recovery_verified']
        write_json(qpath, q)
        pair['qualification']['sha256'] = sha(qpath.read_bytes())
        write_json(args['ota_release'], pair)
    if damage == 'pair':
        pair = json.loads(args['ota_release'].read_text()); pair['main']['sha256'] = '0' * 64
        write_json(args['ota_release'], pair)
    if damage.startswith('report'):
        report = json.loads(args['migration_report'].read_text())
        if damage == 'report': report['recovery_sha256'] = '0' * 64
        if damage == 'report-uid': report['uid'][0] = 0
        if damage == 'report-input': report['sources']['input_manifest']['sha256'] = '0' * 64
        write_json(args['migration_report'], report)
    if damage == 'signature':
        f = path.parent / 'migration.signed.bin'; b = bytearray(f.read_bytes()); b[-1] ^= 1; f.write_bytes(b)
        r = json.loads(args['migration_report'].read_text()); r['artifacts'][f.name]['sha256'] = sha(b); write_json(args['migration_report'], r)
    with pytest.raises(ValueError): package(args)
    assert not args['output'].exists()


def test_never_overwrites_or_writes_inputs(sources):
    args, _ = sources
    args['output'].write_bytes(b'keep')
    with pytest.raises(ValueError): package(args)
    assert args['output'].read_bytes() == b'keep'
    args['output'] = ROOT / 'inputs/android-forbidden.zip'
    with pytest.raises(ValueError): package(args)
    assert not args['output'].exists()


def test_public_kotlin_fixture_signature_and_region_vector():
    fixtures = ROOT / 'apps/android-updater/test-fixtures'
    public = serialization.load_pem_public_key((fixtures / 'synthetic-public.pem').read_bytes())
    vector = json.loads((fixtures / 'hash-vector.json').read_text())
    with zipfile.ZipFile(fixtures / 'synthetic-update.zip') as archive:
        raw = archive.read('manifest.json')
        public.verify(archive.read('manifest.sig'), raw, ec.ECDSA(hashes.SHA256()))
        assert raw == (fixtures / 'manifest.json').read_bytes()
        manifest = json.loads(raw)
        for role in ('migration', 'main'):
            blob = archive.read(manifest[role]['file'])
            end = package_zigbee_ota.image(blob)['authenticated_end']
            assert vector[role] == dict(authenticatedEnd=end, fileSha256=sha(blob), signedRegionSha256=sha(blob[:end]))


def test_historical_source_build_counter_remains_allowed(sources):
    import os
    args, _ = sources
    root = args['device'].parent
    output = root / 'initial.signed.bin'
    subprocess.run([str(package_zigbee_ota.PYTHON), str(package_zigbee_ota.IMGTOOL), 'sign', '--header-size', '512', '--slot-size', '0xa4000', '--align', '4', '--version', '0.5.7+9', '--overwrite-only', '-k', os.environ['VIMAR_SIGNING_PRIVATE_KEY'], str(root / 'initial.raw'), str(output)], check=True, capture_output=True)
    descriptor = json.loads(args['device'].read_text())
    descriptor['initialMain'][0]['sha256'] = sha(output.read_bytes())
    write_json(args['device'], descriptor)
    package(args)
    with zipfile.ZipFile(args['output']) as zipped:
        m = json.loads(zipped.read('manifest.json'))
        end = package_zigbee_ota.image(output.read_bytes())['authenticated_end']
        assert m['allowedSourceSignedHashes'] == [sha(output.read_bytes()[:end])]


def profile2_sources(sources, *, mismatch=None):
    """Exercise both real profile2 validators with temporary signed images."""
    import os
    args, key = sources
    root = args['device'].parent
    for role, version in [('recovery', '0.7.3+0'), ('migration', '0.8.1+0')]:
        subprocess.run([str(package_zigbee_ota.PYTHON), str(package_zigbee_ota.IMGTOOL), 'sign', '--header-size', '512', '--slot-size', '0xa4000', '--align', '4', '--version', version, '--overwrite-only', '-k', os.environ['VIMAR_SIGNING_PRIVATE_KEY'], str(root / (role + '.raw')), str(root / (role + '.signed.bin'))], check=True, capture_output=True)
    recovery = root / 'recovery.signed.bin'
    config = root / 'recovery.config'
    config.write_text('CONFIG_VIMAR_OTA_SPLIT_STAGING=y\nCONFIG_VIMAR_P031_PROTECTION=y\nCONFIG_VIMAR_OTA_INSTALLER=y\nCONFIG_NRF_COMPRESS_LZMA_MAX_DICT_SIZE=32768\n')
    input_data = json.loads(args['migration_input'].read_text())
    actual_loader = input_data['loader_sha256']
    binding = dict(schema_version=1, ota_profile=2, recovery_sha256=sha(recovery.read_bytes()), allowed_loaders=[actual_loader], recovery_config_sha256=sha(config.read_bytes()))
    migration_binding = write_json(root / 'migration-bindings.json', binding)
    release_binding_data = dict(binding)
    if mismatch == 'different-binding': release_binding_data['allowed_loaders'] = [actual_loader, '0' * 64]
    if mismatch == 'unqualified-loader': release_binding_data['allowed_loaders'] = ['0' * 64]
    release_binding = write_json(root / 'release-bindings.json', release_binding_data)
    record = lambda path: dict(path=path.name, sha256=sha(path.read_bytes()))
    input_data.update(schema_version=2, ota_profile=2, recovery_version='0.7.3+0', recovery_sha256=sha(recovery.read_bytes()), pair_bindings=record(migration_binding), recovery_config=record(config))
    write_json(args['migration_input'], input_data)
    evidence = root / 'qualification.json'
    qualification = json.loads(evidence.read_text())
    qualification.update(ota_profile=2, recovery_sha256=sha(recovery.read_bytes()), allowed_loaders=release_binding_data['allowed_loaders'], **{k: True for k in ota_release.SPLIT_REQUIRED_CHECKS})
    write_json(evidence, qualification)
    pair = json.loads(args['ota_release'].read_text())
    pair.update(ota_profile=2, recovery=dict(**record(recovery), version='0.7.3+0'), qualification=record(evidence), pair_bindings=record(release_binding))
    write_json(args['ota_release'], pair)
    validated = build_ota_migration.validate_manifest(args['migration_input'], recovery)
    validated.pop('recovery_bytes')
    migration = root / 'migration.signed.bin'
    write_json(args['migration_report'], dict(validated, schema_version=1, migration_version='0.8.1+0', status='signed ordinary bootstrap verified; hardware qualification pending', artifacts={migration.name: dict(size=migration.stat().st_size, sha256=sha(migration.read_bytes()))}))
    # Both existing validators independently accept these inputs. The generator
    # must additionally prove they describe the same qualified loader pair.
    ota_release.load_ota_pair(args['ota_release'])
    return args, key


def test_profile2_matching_qualified_binding(sources):
    args, key = profile2_sources(sources)
    pair = json.loads(args['ota_release'].read_text())
    pair['main']['version'] = '0.5.8'
    pair['recovery']['version'] = '0.7.3'
    write_json(args['ota_release'], pair)
    package(args)
    with zipfile.ZipFile(args['output']) as zipped:
        raw = zipped.read('manifest.json')
        key.public_key().verify(zipped.read('manifest.sig'), raw, ec.ECDSA(hashes.SHA256()))
        manifest = json.loads(raw)
        assert manifest['migration']['wireVersion'] == [0, 8, 1, 0]
        assert manifest['provenance']['otaReleaseSha256'] == sha(args['ota_release'].read_bytes())


@pytest.mark.parametrize('mismatch', ['different-binding', 'unqualified-loader'])
def test_profile2_independently_valid_but_unmatched_bindings_rejected(sources, mismatch):
    args, _ = profile2_sources(sources, mismatch=mismatch)
    with pytest.raises(ValueError, match='qualified.*(binding|loader)'):
        package(args)
    assert not args['output'].exists()
