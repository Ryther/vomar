"""Synthetic whole-runtime admission tests; no downloads or interpreter execution."""
import hashlib
import io
import json
from pathlib import Path
import tarfile

import pytest

from tools.dev import desktop_runtime as runtime


def archive(tmp_path, entries):
    path = tmp_path / 'runtime.tar.gz'
    with tarfile.open(path, 'w:gz') as output:
        for name, kind, value in entries:
            member = tarfile.TarInfo(name)
            if kind == 'file':
                value = value.encode();member.size = len(value);member.mode = 0o755
                output.addfile(member, io.BytesIO(value))
            elif kind == 'directory':
                member.type = tarfile.DIRTYPE;output.addfile(member)
            else:
                member.type = tarfile.SYMTYPE if kind == 'symlink' else tarfile.LNKTYPE
                member.linkname = value;output.addfile(member)
    return path


def test_whole_runtime_extracts_internal_links_without_crossing_destination(tmp_path):
    source = archive(tmp_path, [('python/bin/python3.13', 'file', 'synthetic interpreter'),
                               ('python/bin/python', 'symlink', 'python3.13')])
    destination = tmp_path / 'selected'
    runtime.extract_verified(source, destination, hashlib.sha256(source.read_bytes()).hexdigest())
    assert (destination / 'python/bin/python').read_text() == 'synthetic interpreter'
    assert (destination / 'python/bin/python3.13').stat().st_mode & 0o100


@pytest.mark.parametrize('entries', [
    [('../outside', 'file', 'escape')], [('/absolute', 'file', 'escape')],
    [('python/../outside', 'file', 'escape')], [('python\\outside', 'file', 'escape')],
    [('python/C:outside', 'file', 'escape')], [('other/file', 'file', 'wrong root')],
    [('python/file', 'file', 'first'), ('python/file', 'file', 'duplicate')],
    [('python/bin/python', 'symlink', '../../../outside')],
    [('python/bin/python', 'symlink', '/outside')],
    [('python/bin/python', 'symlink', 'missing')],
    [('python/a', 'symlink', 'b'), ('python/b', 'symlink', 'a')],
    [('python/a', 'symlink', 'directory'), ('python/a/file', 'file', 'link parent')],
    [('python/a', 'hardlink', 'python/missing')],
])
def test_invalid_archive_is_rejected_before_any_extraction(tmp_path, entries):
    source = archive(tmp_path, entries);destination = tmp_path / 'selected'
    with pytest.raises(ValueError):
        runtime.extract_verified(source, destination, hashlib.sha256(source.read_bytes()).hexdigest())
    assert not destination.exists()
    assert not (tmp_path / 'outside').exists()


def test_checksum_and_resource_limits_are_checked_before_extraction(tmp_path):
    source = archive(tmp_path, [('python/bin/python', 'file', 'synthetic')])
    for digest, limits in [('0' * 64, {}), (hashlib.sha256(source.read_bytes()).hexdigest(), {'max_expanded': 1}),
                           (hashlib.sha256(source.read_bytes()).hexdigest(), {'max_members': 0})]:
        with pytest.raises(ValueError):runtime.extract_verified(source, tmp_path / 'selected', digest, **limits)
        assert not (tmp_path / 'selected').exists()


def test_case_insensitive_target_rejects_colliding_files(tmp_path):
    source = archive(tmp_path, [('python/File', 'file', 'first'), ('python/file', 'file', 'second')])
    with pytest.raises(ValueError):
        runtime.extract_verified(source, tmp_path / 'selected', hashlib.sha256(source.read_bytes()).hexdigest(), case_insensitive=True)
    assert not (tmp_path / 'selected').exists()


def test_existing_output_is_never_reused_or_replaced(tmp_path):
    source = archive(tmp_path, [('python/bin/python', 'file', 'synthetic')])
    destination = tmp_path / 'selected';destination.mkdir();(destination / 'owner').write_text('preserve')
    with pytest.raises(FileExistsError):runtime.extract_verified(source, destination, hashlib.sha256(source.read_bytes()).hexdigest())
    assert (destination / 'owner').read_text() == 'preserve'


def test_environment_removes_old_interpreter_and_loader_overrides(tmp_path):
    base = tmp_path / 'python'
    inherited = {'PATH': '/old/bin', 'PYTHONHOME': '/old', 'PYTHONPATH': '/old/site',
                 'LD_LIBRARY_PATH': '/old/lib', 'LD_PRELOAD': '/old/inject.so',
                 'DYLD_LIBRARY_PATH': '/old/lib', '__PYVENV_LAUNCHER__': '/old/python',
                 'VIRTUAL_ENV': '/old/venv', 'VIMAR_BUILD_PYTHON': '/sdk/python', 'KEEP': 'yes'}
    env = runtime.clean_environment(base, system='Linux', inherited=inherited)
    assert env['LD_LIBRARY_PATH'] == str(base / 'lib')
    assert env['PATH'].split(runtime.os.pathsep)[0] == str(base / 'bin')
    assert all(key not in env for key in ('PYTHONHOME', 'PYTHONPATH', 'LD_PRELOAD', 'DYLD_LIBRARY_PATH', '__PYVENV_LAUNCHER__', 'VIRTUAL_ENV'))
    assert env['VIMAR_BUILD_PYTHON'] == '/sdk/python' and env['KEEP'] == 'yes'
    assert inherited['PYTHONHOME'] == '/old'


@pytest.mark.parametrize('python_version,openssl', [('3.13.12', 'OpenSSL 3.5.9 29 Sep 2026'),
                                                  ('3.13.18', 'OpenSSL 3.0.18 30 Sep 2025')])
def test_runtime_identity_rejects_same_soname_old_runtime(python_version, openssl):
    with pytest.raises(ValueError):runtime.verify_identity({'pythonVersion': python_version, 'opensslVersion': openssl})


def test_catalog_is_exact_for_supported_native_platforms():
    catalog = runtime.catalog()
    assert catalog['pythonVersion'] == '3.13.18' and catalog['opensslVersion'] == '3.5.9'
    assert set(catalog['platforms']) == {'linux-x64', 'windows-x64', 'macos-arm64'}
    assert runtime.platform_key('Darwin', 'arm64') == 'macos-arm64'
    with pytest.raises(ValueError):runtime.platform_key('Darwin', 'x86_64')
    assert runtime.verify_identity({'pythonVersion': '3.13.18', 'opensslVersion': 'OpenSSL 3.5.9 29 Sep 2026'})


def test_receipt_cannot_substitute_an_unpinned_runtime():
    selected = runtime.catalog();entry = selected['platforms']['windows-x64']
    receipt = {'schemaVersion': 1, 'provider': selected['provider'], 'release': selected['release'],
               'platform': 'windows-x64', 'archive': entry, 'sources': selected['sources'],
               'runtime': {'pythonVersion': '3.13.18', 'opensslVersion': 'OpenSSL 3.5.9 29 Sep 2026', 'isolatedEnvironment':True}}
    assert runtime.validate_receipt(receipt, 'windows-x64') == receipt
    receipt = json.loads(json.dumps(receipt));receipt['archive']['sha256'] = '0' * 64
    with pytest.raises(ValueError):runtime.validate_receipt(receipt, 'windows-x64')


def test_ci_export_keeps_venv_first_and_clears_parent_loader_settings(tmp_path, monkeypatch):
    github_env=tmp_path/'env';github_path=tmp_path/'path'
    monkeypatch.setenv('GITHUB_ENV',str(github_env));monkeypatch.setenv('GITHUB_PATH',str(github_path))
    env=runtime.clean_environment(tmp_path/'base/python',system='Linux',venv=tmp_path/'venv',inherited={'PATH':'/old/bin','PYTHONHOME':'/old'})
    runtime.export_github_environment(env)
    # Actions prepends GITHUB_PATH entries in reverse append order.
    assert github_path.read_text().splitlines()[-1]==str(tmp_path/'venv/bin')
    assert 'PYTHONHOME=\n' in github_env.read_text()
    assert 'LD_LIBRARY_PATH='+str(tmp_path/'base/python/lib')+'\n' in github_env.read_text()
