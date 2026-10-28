"""Explicit, isolated desktop CPython bootstrap; SDK and host Python are unchanged."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import subprocess
import tarfile
import urllib.request

CATALOG = Path(__file__).with_name('desktop-runtimes.json')
OVERRIDES = {'PYTHONHOME', 'PYTHONPATH', 'PYTHONUSERBASE', 'PYTHONSTARTUP', 'PYTHONEXECUTABLE',
             '__PYVENV_LAUNCHER__', 'VIRTUAL_ENV', 'LD_LIBRARY_PATH', 'LD_PRELOAD',
             'DYLD_LIBRARY_PATH', 'DYLD_FALLBACK_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES',
             'pythonLocation', 'Python_ROOT_DIR', 'Python2_ROOT_DIR', 'Python3_ROOT_DIR'}


def catalog():
    return json.loads(CATALOG.read_bytes())


def platform_key(system=None, machine=None):
    pair = (system or platform.system(), machine or platform.machine())
    keys = {('Linux', 'x86_64'): 'linux-x64', ('Windows', 'AMD64'): 'windows-x64',
            ('Windows', 'x86_64'): 'windows-x64', ('Darwin', 'arm64'): 'macos-arm64',
            ('Darwin', 'aarch64'): 'macos-arm64'}
    if pair not in keys:raise ValueError('Unsupported desktop runtime platform')
    return keys[pair]


def clean_environment(base, *, system=None, inherited=None, venv=None):
    system = system or platform.system();base = Path(base)
    env = {k: v for k, v in (os.environ if inherited is None else inherited).items() if k not in OVERRIDES}
    paths = [base, base / 'Scripts'] if system == 'Windows' else [base / 'bin']
    if venv is not None:paths.insert(0, Path(venv) / ('Scripts' if system == 'Windows' else 'bin'))
    env['PATH'] = os.pathsep.join([*(str(p) for p in paths), env.get('PATH', '')])
    env['PYTHONNOUSERSITE'] = '1'
    if system == 'Linux':env['LD_LIBRARY_PATH'] = str(base / 'lib')
    return env


def verify_identity(info):
    expected = catalog()
    if not isinstance(info, dict) or info.get('pythonVersion') != expected['pythonVersion'] or not isinstance(info.get('opensslVersion'), str) or not info['opensslVersion'].startswith('OpenSSL ' + expected['opensslVersion'] + ' '):
        raise ValueError('Desktop runtime must use the pinned CPython and OpenSSL versions')
    return True


def validate_receipt(receipt, selected_platform):
    expected = catalog()
    if not isinstance(receipt, dict) or set(receipt) != {'schemaVersion', 'provider', 'release', 'platform', 'archive', 'runtime', 'sources'} or type(receipt['schemaVersion']) is not int or receipt['schemaVersion'] != 1 or receipt['provider'] != expected['provider'] or receipt['release'] != expected['release'] or receipt['platform'] != selected_platform or receipt['archive'] != expected['platforms'].get(selected_platform) or receipt['sources'] != expected['sources']:
        raise ValueError('Desktop runtime provenance does not match the pinned whole runtime')
    verify_identity(receipt['runtime'])
    if receipt['runtime'].get('isolatedEnvironment') is not True:raise ValueError('Desktop runtime requires its isolated environment')
    return receipt


def _member_path(name):
    path = PurePosixPath(name)
    if not name or '\\' in name or ':' in name or path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != 'python':
        raise ValueError('Unsafe desktop runtime archive path')
    return path


def _link_path(member):
    name = member.linkname
    if not name or '\\' in name or ':' in name or name.startswith('/'):
        raise ValueError('Unsafe desktop runtime archive link')
    parts = [] if member.islnk() else list(PurePosixPath(member.name).parent.parts)
    for part in PurePosixPath(name).parts:
        if part == '..':
            if len(parts) <= 1:raise ValueError('Desktop runtime link escapes its root')
            parts.pop()
        elif part != '.':parts.append(part)
    return _member_path('/'.join(parts))


def extract_verified(archive, destination, expected_sha, *, max_members=20000, max_expanded=512*1024*1024, case_insensitive=False):
    """Validate the entire bounded archive before creating any destination file."""
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():raise FileExistsError('Desktop runtime destination must be new')
    if Path(archive).stat().st_size>64*1024*1024:raise ValueError('Desktop runtime archive exceeds download limit')
    with Path(archive).open('rb') as source:
        if hashlib.file_digest(source, 'sha256').hexdigest() != expected_sha:raise ValueError('Desktop runtime archive checksum mismatch')
    with tarfile.open(archive, 'r:gz') as source:
        members = [];names = {};aliases = set();total = 0
        for member in source:
            path = _member_path(member.name)
            key = str(path).casefold() if case_insensitive else str(path)
            if key in aliases or not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                raise ValueError('Duplicate or unsupported desktop runtime archive entry')
            aliases.add(key);names[path] = member;members.append((path, member));total += member.size
            if len(members) > max_members or total > max_expanded or member.size > 64*1024*1024:
                raise ValueError('Desktop runtime archive exceeds extraction limits')
        links = {path: _link_path(member) for path, member in members if member.issym() or member.islnk()}
        for path, member in members:
            if any(parent in links for parent in path.parents):raise ValueError('Desktop runtime member traverses an archive link')
        for path, target in links.items():
            seen = {path}
            while target in links:
                if target in seen:raise ValueError('Cyclic desktop runtime archive link')
                seen.add(target);target = links[target]
            if target not in names or names[path].islnk() and not names[target].isfile():
                raise ValueError('Missing desktop runtime link target')
        destination.mkdir(parents=True)
        try:
            for path, member in members:
                target = destination.joinpath(*path.parts)
                if member.isdir():target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.extractfile(member) as src, target.open('xb') as dst:shutil.copyfileobj(src, dst)
                    target.chmod(member.mode & 0o755)
            for path, member in members:
                if path not in links:continue
                target = destination.joinpath(*path.parts);target.parent.mkdir(parents=True, exist_ok=True)
                if member.issym():target.symlink_to(member.linkname, target_is_directory=names[links[path]].isdir())
                else:os.link(destination.joinpath(*links[path].parts), target)
        except BaseException:
            shutil.rmtree(destination);raise


def _download(item, target):
    total = 0
    with urllib.request.urlopen(item['url'], timeout=120) as source, target.open('xb') as output:
        while chunk := source.read(1024*1024):
            total += len(chunk)
            if total > item['size']:raise ValueError('Desktop runtime download exceeds pinned size')
            output.write(chunk)
    with target.open('rb') as source:actual = hashlib.file_digest(source, 'sha256').hexdigest()
    if total != item['size'] or actual != item['sha256']:raise ValueError('Desktop runtime download identity mismatch')


def _identity(python, env, *, require_venv=False):
    script = 'import json,sys,ssl;print(json.dumps({"pythonVersion":".".join(map(str,sys.version_info[:3])),"opensslVersion":ssl.OPENSSL_VERSION,"isolatedEnvironment":sys.prefix!=sys.base_prefix}))'
    result = subprocess.run([str(python), '-I', '-c', script], env=env, capture_output=True, text=True, check=True, timeout=30)
    info = json.loads(result.stdout);verify_identity(info)
    if require_venv and info.get('isolatedEnvironment') is not True:raise ValueError('Desktop interpreter is outside its isolated environment')
    return info


def bootstrap(destination, *, archive=None):
    destination = Path(destination).absolute()
    if '\n' in str(destination) or '\r' in str(destination):raise ValueError('Single-line desktop runtime path required')
    destination.mkdir(parents=True, exist_ok=False)
    selected = platform_key();item = catalog()['platforms'][selected]
    downloaded = destination / 'runtime.tar.gz'
    if archive is None:_download(item, downloaded)
    else:
        archive = Path(archive)
        if archive.stat().st_size != item['size']:raise ValueError('Desktop runtime archive size mismatch')
        shutil.copyfile(archive, downloaded)
    extract_verified(downloaded, destination / 'base', item['sha256'], case_insensitive=selected != 'linux-x64')
    base = destination / 'base/python';python = base / ('python.exe' if selected == 'windows-x64' else 'bin/python3.13')
    env = clean_environment(base);info = _identity(python, env)
    venv = destination / 'venv'
    subprocess.run([str(python), '-I', '-m', 'venv', '--copies', str(venv)], env=env, check=True, timeout=120)
    env = clean_environment(base, venv=venv)
    info=_identity(venv / ('Scripts/python.exe' if selected == 'windows-x64' else 'bin/python'), env, require_venv=True)
    license_file = destination / 'OpenSSL-LICENSE.txt';_download(catalog()['opensslLicense'], license_file)
    receipt = {'schemaVersion': 1, 'provider': catalog()['provider'], 'release': catalog()['release'],
               'platform': selected, 'archive': item, 'runtime': info, 'sources': catalog()['sources']}
    receipt_path = destination / 'runtime-receipt.json';receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    env['VOMAR_DESKTOP_RUNTIME_RECEIPT'] = str(receipt_path)
    env['VOMAR_DESKTOP_OPENSSL_LICENSE'] = str(license_file)
    return env


def export_github_environment(env):
    """Export only to subsequent steps of this explicitly selected native job."""
    values = {key: env.get(key, '') for key in OVERRIDES | {'PYTHONNOUSERSITE', 'VOMAR_DESKTOP_RUNTIME_RECEIPT', 'VOMAR_DESKTOP_OPENSSL_LICENSE'}}
    if any('\n' in value or '\r' in value for value in values.values()):raise ValueError('Single-line CI runtime environment required')
    with Path(os.environ['GITHUB_ENV']).open('a') as stream:
        stream.write(''.join(key + '=' + value + '\n' for key, value in sorted(values.items())))
    with Path(os.environ['GITHUB_PATH']).open('a') as stream:
        stream.write('\n'.join(reversed(env['PATH'].split(os.pathsep)[:3 if os.name == 'nt' else 2])) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--archive', type=Path, help='Previously downloaded exact pinned archive')
    parser.add_argument('--github-actions', action='store_true')
    args = parser.parse_args();env = bootstrap(args.destination, archive=args.archive)
    if args.github_actions:export_github_environment(env)
    print(json.dumps({'receipt': env['VOMAR_DESKTOP_RUNTIME_RECEIPT'], 'python': shutil.which('python', path=env['PATH'])}))


if __name__ == '__main__':main()
