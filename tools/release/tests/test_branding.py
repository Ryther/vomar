"""Brand distribution detects drift without silently changing source artwork."""
import hashlib
import importlib
import json

import pytest


def branding_module():
    try:
        return importlib.import_module('tools.release.branding')
    except ModuleNotFoundError:
        pytest.fail('The brand synchronization command is not implemented')


def sources(root):
    module = branding_module()
    assets = root/'assets/branding'
    rows = []
    for name in sorted(set(module.COPIES.values()) | {'vomar-icon.png'}):
        data = ('synthetic brand '+name).encode()
        target = assets/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        rows.append({'file': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    (assets/'manifest.json').write_text(json.dumps({'assets': rows}))
    return module


def test_check_reports_missing_and_changed_copies_without_writing(tmp_path):
    module = sources(tmp_path)
    target = tmp_path/'docs/images/vomar-banner.png'
    assert 'docs/images/vomar-banner.png' in module.synchronize(tmp_path, check=True)
    assert not target.exists()
    module.synchronize(tmp_path)
    assert target.read_bytes() == b'synthetic brand vomar-banner.png'
    assert module.synchronize(tmp_path, check=True) == []
    target.write_bytes(b'changed copy')
    assert module.synchronize(tmp_path, check=True) == ['docs/images/vomar-banner.png']
    assert target.read_bytes() == b'changed copy'


def test_invalid_source_hash_never_overwrites_distributed_assets(tmp_path):
    module = sources(tmp_path)
    target = tmp_path/'docs/images/vomar-banner.png'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'existing public banner')
    (tmp_path/'assets/branding/vomar-banner.png').write_bytes(b'corrupt source')
    with pytest.raises(ValueError, match='checksum'):
        module.synchronize(tmp_path)
    assert target.read_bytes() == b'existing public banner'


def test_sync_rejects_destination_symlink_outside_checkout(tmp_path):
    module = sources(tmp_path/'checkout')
    outside = tmp_path/'outside'
    outside.mkdir()
    target = tmp_path/'checkout/docs/images'
    target.parent.mkdir(parents=True)
    target.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        module.synchronize(tmp_path/'checkout')
    assert list(outside.iterdir()) == []
