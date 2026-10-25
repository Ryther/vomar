"""Reviewable public-source boundary independent of Git's tracking state."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess

ROOT=Path(__file__).resolve().parents[2]
PRIVATE_ROOTS={'inputs','analysis','experiments','work','_test','_tmp','.git','.worktrees','.superpowers'}
STATE_NAMES={'node_modules','.gradle','.venv','__pycache__','.pytest_cache','build','builds'}
PUBLIC_KEYS={'firmware/keys/dev-public.pem'}


def validate_path(value: str) -> PurePosixPath:
    if not value or '\\' in value or any(ord(c)<32 for c in value):
        raise ValueError('Invalid public path')
    path=PurePosixPath(value)
    if path.is_absolute() or any(p in ('','..','.') for p in value.split('/')):
        raise ValueError('Path escapes public source')
    if (path.parts[0] in PRIVATE_ROOTS and value!='inputs/README.md') or path.parts[0].startswith(('_test','_tmp')):
        raise ValueError('Private research path')
    if any(part in STATE_NAMES for part in path.parts):
        raise ValueError('Generated/private state path')
    if value.startswith(('.codex/auth','.codex/history','.codex/sessions','.claude/settings.local','.impeccable/')):
        raise ValueError('Private assistant state')
    if path.name.startswith('core.') or path.name=='core' or path.name.startswith('.env') and path.name!='.env.example':
        raise ValueError('Private runtime/environment data')
    suffix=path.suffix.lower()
    if suffix in {'.jks','.keystore','.p12','.pfx','.key','.dmp','.hprof','.heapdump','.log'} or '-private.' in path.name:
        raise ValueError('Signing secret or runtime dump')
    if suffix=='.pem' and value not in PUBLIC_KEYS and not (
        value.startswith('apps/android-updater/test-fixtures/synthetic-') and path.name.endswith('-public.pem')
    ):
        raise ValueError('Unreviewed PEM')
    if suffix in {'.bin','.hex','.elf','.apk','.aab','.apks','.o','.a','.so','.dll','.dylib'}:
        raise ValueError('Compiled/acquired artifacts belong in release assets')
    if suffix=='.jar' and value!='apps/android-updater/gradle/wrapper/gradle-wrapper.jar':
        raise ValueError('Unreviewed executable archive')
    if suffix=='.zip' and not (
        value.startswith('apps/android-updater/test-fixtures/synthetic-')
        or value.startswith('apps/android-updater/app/src/androidTest/assets/synthetic-')
        or value.startswith('tools/android/test-fixtures/')
        or value.startswith('tests/contracts/fixtures/')
    ):
        raise ValueError('Only reviewed synthetic archives are source')
    return path


def source_files(root: Path=ROOT, *, untracked: bool=False) -> list[str]:
    command=['git','-C',str(root),'ls-files','-z']
    if untracked:
        command+=['--cached','--others','--exclude-standard']
    names=sorted(set(x.decode('utf-8') for x in subprocess.check_output(command).split(b'\0') if x))
    for name in names:
        validate_path(name)
        if subprocess.run(['git','-C',str(root),'check-ignore','--no-index','--quiet','--',name]).returncode==0:
            raise ValueError('Tracked private/ignored source: '+name)
        path=root/name
        if path.is_symlink() and not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Public symlink escapes source root: '+name)
        if not path.is_symlink() and not path.is_file():
            raise ValueError('Non-regular public source: '+name)
    return names


def manifest(root: Path=ROOT, *, untracked: bool=False) -> dict:
    rows=[]
    for name in source_files(root,untracked=untracked):
        path=root/name
        raw=str(path.readlink()).encode() if path.is_symlink() else path.read_bytes()
        rows.append(dict(path=name,size=len(raw),sha256=hashlib.sha256(raw).hexdigest(),
                         kind='symlink' if path.is_symlink() else 'file'))
    return dict(schemaVersion=1,commit=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip(),files=rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--include-untracked',action='store_true')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    value=manifest(untracked=args.include_untracked)
    text=json.dumps(value,indent=2)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(text)
    else:
        print(text,end='')


if __name__=='__main__':
    main()
