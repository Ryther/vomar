"""Synchronize reviewed brand artwork without image conversions or dependencies."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
COPIES = {
    'docs/images/vomar-banner.png': 'vomar-banner.png',
    'docs/images/vomar-icon.png': 'png-sizes/vomar-icon-128.png',
    'docs/images/vomar.ico': 'vomar.ico',
    'apps/android-updater/app/src/main/res/drawable-nodpi/vomar_icon.png': 'png-sizes/vomar-icon-512.png',
    **{f'apps/desktop-updater/src/vomar_updater/resources/vomar-icon-{size}.png':
       f'png-sizes/vomar-icon-{size}.png' for size in SIZES},
}


def local_path(root: Path, name: str) -> Path:
    path = root/name
    if any(parent.is_symlink() for parent in (path, *path.parents) if parent != root and parent.is_relative_to(root)):
        raise ValueError('Brand paths must not contain a symlink: '+name)
    return path


def synchronize(root: Path = ROOT, *, check: bool = False) -> list[str]:
    """Return stale destinations; check mode never writes, including missing files."""
    root = root.resolve()
    manifest = json.loads(local_path(root, 'assets/branding/manifest.json').read_text())
    expected = set(COPIES.values()) | {'vomar-icon.png'}
    rows = manifest['assets']
    if len(rows) != len(expected) or {row['file'] for row in rows} != expected:
        raise ValueError('Unexpected brand manifest asset paths')
    sources = {}
    for row in rows:
        name = row['file']
        data = local_path(root, 'assets/branding/'+name).read_bytes()
        if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('Brand source checksum mismatch: '+name)
        sources[name] = data
    # Inspect every destination before writing any copy.
    targets = {name: local_path(root, name) for name in COPIES}
    stale = [name for name, path in targets.items()
             if not path.is_file() or path.read_bytes() != sources[COPIES[name]]]
    if not check:
        for name in stale:
            path = targets[name]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(sources[COPIES[name]])
    return stale


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true', help='Report drift without writing')
    mode.add_argument('--sync', action='store_true', help='Copy verified original bytes to consumers')
    args = parser.parse_args()
    try:
        stale = synchronize(check=args.check)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    if args.check and stale:
        print('Stale brand copies:\n'+'\n'.join(stale), file=sys.stderr)
        return 1
    print('Brand artwork verified.' if args.check else f'Synchronized {len(stale)} brand assets.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
