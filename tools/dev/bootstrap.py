"""Explicit development bootstrap; never touches hardware or production keys."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = next((p for p in Path(__file__).resolve().parents if (p/'firmware/west.yml').is_file()), Path.cwd())


def run(*args, cwd=None):
    subprocess.run([str(a) for a in args], cwd=cwd, check=True)


def download(item, dest):
    if not item['url'].startswith('https://'):
        raise ValueError('HTTPS tool URL required')
    with urllib.request.urlopen(item['url'],timeout=120) as r, open(dest,'wb') as out:
        shutil.copyfileobj(r,out)
    if hashlib.file_digest(open(dest,'rb'),'sha256').hexdigest()!=item['sha256']:
        Path(dest).unlink()
        raise ValueError('Tool checksum mismatch')


def unpack(archive, dest):
    dest=Path(dest);dest.mkdir(parents=True,exist_ok=True)
    def check(name):
        p=PurePosixPath(name)
        if '\\' in name or p.is_absolute() or '..' in p.parts or ':' in name:
            raise ValueError('Unsafe archive member')
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            for i in z.infolist():
                check(i.filename)
                if (i.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('Archive link forbidden')
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            for i in t.getmembers():
                check(i.name)
                if not (i.isfile() or i.isdir() or i.issym() or i.islnk()):raise ValueError('Archive devices forbidden')
                if i.issym() or i.islnk():
                    link=Path(i.linkname)
                    base=dest/i.name if i.islnk() else (dest/i.name).parent
                    target=(dest/link) if i.islnk() else (base/link)
                    if link.is_absolute() or '\\' in i.linkname or not target.resolve().is_relative_to(dest.resolve()):raise ValueError('Archive link escapes destination')
            t.extractall(dest,filter='data')


def install_guide(source, dest, *, symlink=True):
    source=Path(source).resolve();dest=Path(dest)
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    receipt=dest.with_suffix('.vomar-owned.json')
    if dest.is_symlink():
        if dest.resolve()!=source: raise ValueError('User skill already exists')
        return
    if dest.exists():
        old=json.loads(receipt.read_text()) if receipt.exists() else {}
        if hashlib.sha256(dest.read_bytes()).hexdigest()!=old.get('sha256'):
            raise ValueError('User-customized skill must not be overwritten')
    dest.parent.mkdir(parents=True,exist_ok=True)
    if symlink and not dest.exists():
        try: dest.symlink_to(os.path.relpath(source,dest.parent));return
        except OSError: pass
    dest.write_bytes(source.read_bytes());receipt.write_text(json.dumps({'sha256':digest}))


def cache():
    p=Path(os.environ.get('VOMAR_CACHE',Path.home()/'.cache/vomar')).expanduser()
    p.mkdir(parents=True,exist_ok=True);return p


def workspace():
    base=cache();env=base/'dev-venv'
    if not env.exists(): run(sys.executable,'-m','venv',env)
    python=env/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    lock=ROOT/'requirements-dev.lock'
    receipt=env/'vomar-lock.sha256';digest=hashlib.sha256(lock.read_bytes()).hexdigest()
    if not receipt.exists() or receipt.read_text()!=digest:
        run(python,'-m','pip','install','--require-hashes','-r',lock);receipt.write_text(digest)
    state=Path.home()/'.local/share/vomar-agents';state.mkdir(parents=True,exist_ok=True)
    for name in ('.codex','.claude','.config/opencode','.local/share/opencode'):
        dest=Path.home()/name;target=state/name
        target.mkdir(parents=True,exist_ok=True);dest.parent.mkdir(parents=True,exist_ok=True)
        if not dest.exists():
            try:dest.symlink_to(target,target_is_directory=True)
            except OSError:print('Assistant state remains in its private OS-managed home directory.')
    for dest in (Path.home()/'.claude/skills/vomar-guide/SKILL.md',Path.home()/'.config/opencode/skills/vomar-guide/SKILL.md',Path.home()/'.agents/skills/vomar-guide/SKILL.md'):
        install_guide(ROOT/'.agents/skills/vomar-guide/SKILL.md',dest,symlink=os.name!='nt')
    print(f'Development environment: {python}. Agent login remains private.')


def image(catalog):
    m=json.loads(Path(catalog).read_text())
    with tempfile.TemporaryDirectory() as d:
        d=Path(d);archive=d/'python.tar.xz';download(m['python'],archive);unpack(archive,d/'python')
        source=next((d/'python').iterdir())
        run('./configure','--prefix=/opt/python','--enable-shared','LDFLAGS=-Wl,-rpath=/opt/python/lib','--with-ensurepip=install',cwd=source)
        run('make',f'-j{min(os.cpu_count() or 2,8)}',cwd=source);run('make','install',cwd=source)
        arch={'x86_64':'x64','aarch64':'arm64'}.get(platform.machine())
        if arch is None: raise ValueError('Unsupported development architecture')
        item=m['node'][f'node-v24.22.1-linux-{arch}.tar.xz'];archive=d/'node.tar.xz';download(item,archive)
        # Official Node distributions contain internal symlinks: GNU tar follows
        # only the checksum-verified, upstream-owned image archive here.
        Path('/opt/node').mkdir();run('tar','-xf',archive,'--strip-components=1','-C','/opt/node')


def android(m):
    base=cache()/'android';tools=base/'cmdline-tools'/'latest'
    if not tools.exists():
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);p=d/'tools.zip';download(m['android'],p);unpack(p,d/'out')
            tools.parent.mkdir(parents=True,exist_ok=True);shutil.move(d/'out/cmdline-tools',tools)
            for p in (tools/'bin').iterdir(): p.chmod(p.stat().st_mode|0o111)
    print(f'Read/accept licenses: {tools}/bin/sdkmanager --sdk_root={base} --licenses')
    print(f'Then: {tools}/bin/sdkmanager --sdk_root={base} "platforms;android-37.0" "build-tools;36.0.0" "platform-tools"')


def firmware(m):
    if platform.system()!='Linux' or platform.machine()!='x86_64':
        raise ValueError('Use the x64 Linux devcontainer for the pinned Nordic toolchain')
    base=cache();env=base/'ncs-venv';sdk=base/'zephyr-sdk-1.0.1';ws=base/'ncs'
    if not env.exists(): run(sys.executable,'-m','venv',env)
    python=env/'bin/python';west=env/'bin/west'
    run(python,'-m','pip','install','west==1.5.0')
    lock=ROOT/'firmware/west-lock.yml'
    manifest=ws/'vomar-manifest';manifest.mkdir(parents=True,exist_ok=True)
    managed=manifest/'west.yml';managed.write_bytes(lock.read_bytes())
    if not (ws/'.west').exists():run(west,'init','-l',manifest)
    run(west,'config','manifest.path','vomar-manifest',cwd=ws)
    run(west,'config','manifest.file','west.yml',cwd=ws)
    run(west,'update',cwd=ws)
    run(python,'-m','pip','install','-r',ws/'zephyr/scripts/requirements.txt','-r',ws/'nrf/scripts/requirements.txt')
    if not sdk.exists():
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);a=d/'sdk.tar.xz';download(m['sdk'],a);unpack(a,d/'out');shutil.move(d/'out/zephyr-sdk-1.0.1',sdk)
        run(sdk/'setup.sh','-t','arm-zephyr-eabi','-h','-c',cwd=sdk)
    run(west,'zephyr-export',cwd=ws)
    print(f'NCS graph ready at {ws}; set ZEPHYR_SDK_INSTALL_DIR={sdk}')


def main():
    action=sys.argv[1] if len(sys.argv)>1 else 'help'
    if action=='image': image(sys.argv[2]);return
    m=json.loads((ROOT/'.devcontainer/toolchain.json').read_text())
    if action=='workspace': workspace()
    elif action=='android': android(m)
    elif action=='firmware': firmware(m)
    else: raise SystemExit('Usage: bootstrap.py workspace|android|firmware')

if __name__=='__main__': main()
