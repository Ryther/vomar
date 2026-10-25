"""Device-bound migration packaging; no physical device access."""
from local_inputs import local_input, sdk_root
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('build_ota_migration', ROOT / 'tools/firmware/build_ota_migration.py')
builder = importlib.util.module_from_spec(spec)


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def migration_inputs(tmp_path):
    from tools.firmware.toolchain_paths import toolchain_paths
    paths = toolchain_paths()
    sdk_python = local_input(paths['python'])
    imgtool = local_input(sdk_root() / 'bootloader/mcuboot/scripts/imgtool.py')
    local_input(paths['private_key'])
    raw = tmp_path / 'recovery.bin'
    payload = struct.pack('<II', 0x20010000, 0xb0201) + bytes(1016)
    raw.write_bytes(bytes(512) + payload)
    recovery = tmp_path / 'recovery.signed.bin'
    subprocess.run([str(sdk_python), str(imgtool), 'sign', '--header-size', '512',
                    '--slot-size', '0x40000', '--align', '4', '--version', '0.7.1+0',
                    '--overwrite-only', '-k', str(paths['private_key']),
                    str(raw), str(recovery)], check=True, capture_output=True)
    restore = tmp_path / 'restore'
    restore.mkdir()
    # A tiny normalized loader fixture proves file and raw-flash hashes differ.
    (restore / 'loader.hex').write_text(':0400000001020304F2\n:00000001FF\n')
    loader = bytearray(bytes([1, 2, 3, 4]) + b'\xff' * (0xc000 - 4))
    loader[0x9000] = 0x35  # preserved stock bytes outside loader.hex must be pinned
    (tmp_path / 'loader.bin').write_bytes(loader)
    (restore / 'restorer.signed.bin').write_bytes(recovery.read_bytes())
    authorization = dict(deviceid=['11223344', '55667788'], flash_sha256='a'*64,
                         artifacts={name: dict(sha256=sha((restore / name).read_bytes()),
                                               size=(restore / name).stat().st_size)
                                    for name in ('loader.hex', 'restorer.signed.bin')})
    auth_path = restore / 'artifact-manifest.json'
    auth_path.write_text(json.dumps(authorization))
    manifest = dict(schema_version=1, uid=['11223344', '55667788'],
                    loader_path=str(tmp_path / 'loader.bin'), loader_sha256=sha(loader),
                    restore_manifest_path=str(auth_path), restore_manifest_sha256=sha(auth_path.read_bytes()),
                    stock_restore_digest=sha(recovery.read_bytes()), recovery_sha256=sha(recovery.read_bytes()),
                    recovery_version='0.7.1+0')
    path = tmp_path / 'migration.json'
    path.write_text(json.dumps(manifest))
    return path, recovery, manifest


def load():
    spec.loader.exec_module(builder)
    return builder


def test_slot_version_matches_triple_without_ignoring_legacy_build():
    from test_ota_image import fixture
    p = load()
    payload = struct.pack('<II', 0x20010000, 0xc209) + bytes(1000)
    _, ordinary = fixture(payload=payload, version=(0, 5, 8, 0), target=None)
    assert p.check_slot(ordinary, 0xc000, 0xa4000, '0.5.8')['version'] == '0.5.8+0'
    _, historical = fixture(payload=payload, version=(0, 5, 7, 9), target=None)
    assert p.check_slot(historical, 0xc000, 0xa4000, '0.5.7+9')['version'] == '0.5.7+9'
    for claim in ['0.5.7', '0.5.7+0', '0.5.7+8', 'bad']:
        with pytest.raises(ValueError, match='version'):
            p.check_slot(historical, 0xc000, 0xa4000, claim)


def test_prepare_exact_identity_and_recovery(migration_inputs, tmp_path):
    p = load()
    manifest, recovery, contents = migration_inputs
    output = tmp_path / 'output'
    result = p.prepare_migration(manifest, recovery, output)
    generated = output / 'generated'
    uid = (generated / 'target_uid.h').read_text()
    assert '#define MIGRATION_UID0 0x11223344u' in uid
    assert '#define MIGRATION_UID1 0x55667788u' in uid
    assert 'expected_loader_sha256[32]' in uid
    assert 'expected_restorer_sha256[32]' in uid
    assert 'expected_recovery_sha256[32]' in uid
    blob = (generated / 'recovery_blob.h').read_text()
    assert f'#define RECOVERY_BLOB_SIZE {recovery.stat().st_size}u' in blob
    assert (output / 'recovery-0.7.1.signed.bin').read_bytes() == recovery.read_bytes()
    report = json.loads(Path(result['manifest_path']).read_text())
    assert report['loader_sha256'] == contents['loader_sha256']
    assert report['hardware_qualified'] is False
    assert report['recovery_sha256'] == sha(recovery.read_bytes())
    assert not list(output.rglob('*.pem'))


@pytest.mark.parametrize('field,value', [('uid', ['11223344', '55667789']),
    ('loader_sha256', '0'*64), ('stock_restore_digest', '0'*64),
    ('restore_manifest_sha256', '0'*64), ('recovery_sha256', '0'*64), ('recovery_version', '0.7.0+0')])
def test_manifest_mismatch_has_no_output(migration_inputs, tmp_path, field, value):
    p = load()
    manifest, recovery, contents = migration_inputs
    contents[field] = value
    manifest.write_text(json.dumps(contents))
    output = tmp_path / 'rejected'
    with pytest.raises(ValueError):
        p.prepare_migration(manifest, recovery, output)
    assert not output.exists()


def test_tampered_recovery_signature_has_no_output(migration_inputs, tmp_path):
    p = load()
    manifest, recovery, contents = migration_inputs
    data = bytearray(recovery.read_bytes())
    data[-1] ^= 1
    recovery.write_bytes(data)
    contents['recovery_sha256'] = sha(data)
    manifest.write_text(json.dumps(contents))
    output = tmp_path / 'rejected'
    with pytest.raises(ValueError, match='signature'):
        p.prepare_migration(manifest, recovery, output)
    assert not output.exists()


def test_raw_loader_must_match_every_authorized_hex_byte(migration_inputs, tmp_path):
    p = load()
    manifest, recovery, contents = migration_inputs
    raw_path = Path(contents['loader_path'])
    raw = bytearray(raw_path.read_bytes())
    raw[0] ^= 1
    raw_path.write_bytes(raw)
    contents['loader_sha256'] = sha(raw)
    manifest.write_text(json.dumps(contents))
    output = tmp_path / 'rejected-loader'
    with pytest.raises(ValueError, match='loader'):
        p.prepare_migration(manifest, recovery, output)
    assert not output.exists()


def test_snapshot_provenance_must_reproduce_actual_loader(migration_inputs, tmp_path):
    p = load()
    manifest, recovery, contents = migration_inputs
    snapshot = tmp_path / 'after-flash.bin'
    snapshot.write_bytes(b'\xff' * 0x100000)
    contents.update(source_snapshot=str(snapshot), source_snapshot_sha256=sha(snapshot.read_bytes()),
                    transformation='first0xc000bytesverbatim')
    manifest.write_text(json.dumps(contents))
    output = tmp_path / 'bad-provenance'
    with pytest.raises(ValueError, match='snapshot'):
        p.prepare_migration(manifest, recovery, output)
    assert not output.exists()

def profile2_inputs(migration_inputs,tmp_path):
    from test_ota_image import fixture
    path,recovery,d=migration_inputs
    _,raw=fixture(payload=struct.pack('<II',0x20010000,0xb0209)+bytes(1000),version=(0,7,3,0),target=None)
    recovery.write_bytes(raw)
    cfg=tmp_path/'recovery.config';cfg.write_text('CONFIG_VIMAR_OTA_SPLIT_STAGING=y\nCONFIG_VIMAR_P031_PROTECTION=y\nCONFIG_VIMAR_OTA_INSTALLER=y\nCONFIG_NRF_COMPRESS_LZMA_MAX_DICT_SIZE=32768\n')
    report=tmp_path/'pair.json';report.write_text(json.dumps({'schema_version':1,'ota_profile':2,'recovery_sha256':sha(raw),'allowed_loaders':[d['loader_sha256']],'recovery_config_sha256':sha(cfg.read_bytes())}))
    d.update(schema_version=2,ota_profile=2,recovery_version='0.7.3+0',recovery_sha256=sha(raw),pair_bindings={'path':str(report),'sha256':sha(report.read_bytes())},recovery_config={'path':str(cfg),'sha256':sha(cfg.read_bytes())})
    path.write_text(json.dumps(d));return path,recovery,d

def test_profile2_migration_pins_correct_pair_and_native_config(migration_inputs,tmp_path):
    p=load();path,recovery,d=profile2_inputs(migration_inputs,tmp_path)
    r=p.prepare_migration(path,recovery,tmp_path/'split-out')
    report=json.loads(Path(r['manifest_path']).read_text())
    assert report['ota_profile']==2 and report['migration_version']=='0.8.1+0' and report['hardware_qualified'] is False
    assert report['recovery_version']=='0.7.3+0'

@pytest.mark.parametrize('damage',['profile','pair_hash','config_hash','unapproved_loader'])
def test_profile2_migration_rejects_incompatible_pair_before_output(migration_inputs,tmp_path,damage):
    p=load();path,recovery,d=profile2_inputs(migration_inputs,tmp_path)
    if damage=='profile':d['ota_profile']=1
    if damage=='pair_hash':d['pair_bindings']['sha256']='00'*32
    if damage=='config_hash':d['recovery_config']['sha256']='00'*32
    if damage=='unapproved_loader':
        f=Path(d['pair_bindings']['path']);v=json.loads(f.read_text());v['allowed_loaders']=['00'*32];f.write_text(json.dumps(v));d['pair_bindings']['sha256']=sha(f.read_bytes())
    path.write_text(json.dumps(d))
    with pytest.raises(ValueError):p.prepare_migration(path,recovery,tmp_path/'rejected-split')
    assert not (tmp_path/'rejected-split').exists()

def test_split_migration_rejects_build_without_effective_persistent_backend():
    p=load()
    with pytest.raises(ValueError,match='SETTINGS_NVS'):
        p.validate_split_migration_config({'CONFIG_VIMAR_OTA_SPLIT_STAGING':'y','CONFIG_VIMAR_P031_PROTECTION':'y','CONFIG_SETTINGS':'y','CONFIG_SETTINGS_NONE':'y'})
