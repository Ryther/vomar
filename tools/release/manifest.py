"""Strict public distribution manifest; signed firmware remains independently verified."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re

SEMVER = r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'
REQUIRED_ROLES = frozenset(('firmware-common','zigbee-ota','android-apk','desktop-linux-x64','desktop-windows-x64','desktop-macos-x64','desktop-macos-arm64','zigbee2mqtt-converter','licenses','offline-guide'))
OPTIONAL_ROLES = frozenset(('desktop-windows-setup','source-sbom'))
TOP = {'schemaVersion','distributionVersion','tag','commit','components','artifacts'}
ARTIFACT = {'role','filename','size','sha256','componentVersion'}


def loads(raw):
    def pairs(a):
        out={}
        for k,v in a:
            if k in out: raise ValueError('Duplicate JSON field')
            out[k]=v
        return out
    try:return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite number')))
    except (json.JSONDecodeError,UnicodeError) as e:raise ValueError('Invalid JSON') from e


def exact(value, fields, optional=()):
    if type(value) is not dict or not fields<=value.keys() or value.keys()-fields-set(optional):
        raise ValueError('Missing or unknown manifest fields')


def digest(data):return hashlib.sha256(data).hexdigest()


def validate(value, directory=None):
    exact(value,TOP)
    if type(value['schemaVersion']) is not int or value['schemaVersion']!=1:raise ValueError('Unsupported distribution schema')
    version=value['distributionVersion']
    if not isinstance(version,str) or not re.fullmatch(SEMVER,version) or value['tag']!='v'+version:raise ValueError('Version/tag mismatch')
    if not isinstance(value['commit'],str) or not re.fullmatch('[0-9a-f]{40}',value['commit']):raise ValueError('Full immutable commit required')
    if type(value['components']) is not dict or not value['components']:raise ValueError('Component versions required')
    for k,v in value['components'].items():
        if not re.fullmatch('[a-z][a-z0-9-]*',k) or not isinstance(v,str) or not re.fullmatch(SEMVER,v):raise ValueError('Invalid component version')
    if type(value['artifacts']) is not list or not 10<=len(value['artifacts'])<=32:raise ValueError('Incomplete or oversized distribution')
    roles=set();names=set()
    for a in value['artifacts']:
        exact(a,ARTIFACT,{'platform','architecture'})
        role=a['role'];name=a['filename']
        if role not in REQUIRED_ROLES|OPTIONAL_ROLES or role in roles:raise ValueError('Unknown/duplicate artifact role')
        if not isinstance(name,str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,159}',name) or name in names:raise ValueError('Unsafe/duplicate asset name')
        if type(a['size']) is not int or not 0<a['size']<=2**31:raise ValueError('Artifact size outside bounds')
        if not isinstance(a['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',a['sha256']):raise ValueError('Invalid artifact hash')
        if not isinstance(a['componentVersion'],str) or not re.fullmatch(SEMVER,a['componentVersion']):raise ValueError('Invalid component version')
        if role.startswith('desktop-'):
            _,os_name,arch=role.split('-')
            if arch=='setup':arch='x64'
            if a.get('platform')!=os_name or a.get('architecture')!=arch:raise ValueError('Desktop platform mismatch')
        elif 'platform' in a or 'architecture' in a:raise ValueError('Unexpected platform fields')
        if directory is not None:
            path=Path(directory)/name
            if path.is_symlink() or not path.is_file() or path.stat().st_size!=a['size'] or digest(path.read_bytes())!=a['sha256']:raise ValueError('Artifact bytes mismatch: '+role)
        roles.add(role);names.add(name)
    if not REQUIRED_ROLES<=roles:raise ValueError('Missing required artifact roles')
    return value


def build_manifest(version,commit,records,directory,components=None):
    artifacts=[]
    for a in records:
        name=a.get('filename','')
        if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,159}',name):raise ValueError('Unsafe artifact name')
        p=Path(directory)/name
        if p.is_symlink() or not p.is_file():raise ValueError('Regular artifact required')
        artifacts.append({**a,'size':p.stat().st_size,'sha256':digest(p.read_bytes())})
    return validate({'schemaVersion':1,'distributionVersion':version,'tag':'v'+version,'commit':commit,'components':components or {'firmware':'1.0.0','android':'1.0.0','desktop':'1.0.0'},'artifacts':sorted(artifacts,key=lambda a:a['role'])},directory)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path);p.add_argument('--directory',type=Path);a=p.parse_args()
    validate(loads(a.manifest.read_bytes()),a.directory);print('Distribution manifest verified')

if __name__=='__main__':main()
