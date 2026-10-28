"""Download an exact, already frozen experimental draft; never build or publish."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re

from .manifest import SEMVER, REQUIRED_ROLES, digest, loads, validate
from .publish import GitHub, select_draft, require_accepted_notice


def download_draft(remote,version,sha,directory):
    if not re.fullmatch(SEMVER,version) or not re.fullmatch('[0-9a-f]{40}',sha):
        raise ValueError('Ordinary distribution version and full immutable SHA required')
    directory=Path(directory).absolute()
    if any(p.is_symlink() for p in (directory,*directory.parents)):
        raise ValueError('Draft destination cannot contain a symlink')
    if directory.exists():raise FileExistsError(directory)
    tag='v'+version
    release=select_draft(remote.releases(),tag,sha)
    require_accepted_notice(release)
    if remote.tag_sha(tag)!=sha:raise ValueError('Draft tag differs from the exact candidate')
    rows=remote.assets(release['id'])
    if type(rows) is not list or len(rows)!=14:raise ValueError('Exactly fourteen frozen draft assets required')
    by_name={}
    for asset in rows:
        name=asset.get('name')
        if not isinstance(name,str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,159}',name) or name in by_name:
            raise ValueError('Unsafe or duplicate draft asset name')
        if type(asset.get('size')) is not int or not 0<asset['size']<=2**31:
            raise ValueError('Draft asset size outside bounds')
        by_name[name]=asset
    metadata=by_name.get('release-manifest.json')
    if not metadata or metadata['size']>65536:raise ValueError('Bounded distribution manifest required')
    raw=remote.download(metadata)
    if type(raw) is not bytes or len(raw)!=metadata['size']:raise ValueError('Manifest download size mismatch')
    manifest=validate(loads(raw))
    if manifest['commit']!=sha or manifest['distributionVersion']!=version:
        raise ValueError('Manifest belongs to another exact distribution')
    artifacts={a['filename']:a for a in manifest['artifacts']}
    if {a['role'] for a in manifest['artifacts']}!=REQUIRED_ROLES|{'source-sbom','release-acceptance'}:
        raise ValueError('Complete experimental payload and owner acceptance required')
    if artifacts.keys() & {'release-manifest.json','SHA256SUMS'}:
        raise ValueError('Payload cannot replace distribution metadata')
    if by_name.keys()!=artifacts.keys()|{'release-manifest.json','SHA256SUMS'}:
        raise ValueError('Missing or unreviewed extra draft assets')
    for name,artifact in artifacts.items():
        if by_name[name]['size']!=artifact['size']:raise ValueError('Draft size differs from the frozen manifest')
    directory.mkdir(parents=True,exist_ok=False)
    (directory/'release-manifest.json').write_bytes(raw)
    for name,artifact in sorted(artifacts.items()):
        data=remote.download(by_name[name])
        if type(data) is not bytes or len(data)!=artifact['size'] or digest(data)!=artifact['sha256']:
            raise ValueError('Draft payload differs from the frozen manifest')
        with (directory/name).open('xb') as stream:stream.write(data)
    checksums=remote.download(by_name['SHA256SUMS'])
    names=sorted([*artifacts,'release-manifest.json'])
    expected=''.join(digest((directory/name).read_bytes())+'  '+name+'\n' for name in names).encode()
    if checksums!=expected or len(checksums)!=by_name['SHA256SUMS']['size']:
        raise ValueError('Draft checksums do not match the complete payload set')
    with (directory/'SHA256SUMS').open('xb') as stream:stream.write(checksums)
    validate(manifest,directory)
    current=select_draft(remote.releases(),tag,sha)
    require_accepted_notice(current)
    if current['id']!=release['id'] or remote.tag_sha(tag)!=sha:
        raise ValueError('Draft identity changed during download')
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sha',required=True);parser.add_argument('--version',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();token=os.environ.get('GH_TOKEN')
    if not token:raise ValueError('Protected draft read credential required')
    download_draft(GitHub('Ryther/vomar',token),args.version,args.sha,args.output)
    print('Downloaded fourteen immutable experimental draft files; nothing published')


if __name__=='__main__':main()
