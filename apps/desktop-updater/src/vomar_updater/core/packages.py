"""Immutable signed package admission using the firmware's reference validators.

Imports reference parsing/cryptography only. No runtime path calls west, signing,
Gradle, private builders or SDKs. Frozen builds collect these imports explicitly.
"""
from __future__ import annotations
from dataclasses import dataclass
from .admission import seal,require
import io
import json
import re
import zipfile
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from tools.firmware.bounded_zip import read_member
from tools.firmware.package_common_android_update_v3 import strict_json, validate_common_v3_bundle, verify_signature, canonical, sha, exact
from tools.firmware.package_common_android_update import verify_component, verify_zigbee_carrier, hashes_list, digest
from tools.firmware.package_android_update import MAX_ZIP, MAX_IMAGE


def read_bounded(path,limit=MAX_ZIP):
    with Path(path).open('rb') as stream:raw=stream.read(limit+1)
    if len(raw)>limit:raise ValueError('Document exceeds the supported input bound')
    return raw


def version(value):
    if not isinstance(value,str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)',value):raise ValueError('Ordinary SemVer required')
    return tuple(map(int,value.split('.')))


def read_zip(raw, *, limits=None, max_size=MAX_ZIP):
    if not isinstance(raw,bytes) or not 22<=len(raw)<=max_size:raise ValueError('Bounded ZIP required')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            infos=z.infolist();names=[i.filename for i in infos]
            if not 1<=len(infos)<=16 or len(set(names))!=len(names):raise ValueError('Duplicate/oversized ZIP directory')
            if any(i.is_dir() or i.flag_bits&1 or i.filename not in (limits or names) or '/' in i.filename or '\\' in i.filename or i.filename in ('.','..') or i.file_size>(limits[i.filename] if limits else MAX_IMAGE) or (i.external_attr>>16)&0o170000==0o120000 for i in infos):raise ValueError('Unsafe ZIP member')
            if sum(i.file_size for i in infos)>max_size:raise ValueError('ZIP expansion limit')
            return {i.filename:read_member(z,i,limits[i.filename] if limits else MAX_IMAGE) for i in infos}
    except (zipfile.BadZipFile,RuntimeError,NotImplementedError,OSError) as e:raise ValueError('Invalid ZIP') from e


@dataclass(frozen=True)
class Package:
    raw:bytes
    manifest_json:bytes
    digest:str
    schema:int
    model:str
    version:str
    _seal:bytes=b''
    def assert_verified(self):require(self._seal,seal("package",self.raw,self.manifest_json,self.digest,self.schema,self.model,self.version))
    @property
    def manifest(self):return strict_json(self.manifest_json)
    def entries(self):return read_zip(self.raw)
    def image(self,role):return self.entries()[self.manifest[role]['file']]


def inspect_package(raw,public_key,app_version='1.0.0'):
    if not isinstance(raw,bytes):raise ValueError('Immutable package bytes required')
    key=(serialization.load_pem_public_key(public_key) if public_key.startswith(b'-----') else serialization.load_der_public_key(public_key))
    if not isinstance(key,ec.EllipticCurvePublicKey) or not isinstance(key.curve,ec.SECP256R1):raise ValueError('Pinned P256 anchor required')
    entries=read_zip(raw);mraw=entries.get('manifest.json',b'')
    if not 1<=len(mraw)<=65536:raise ValueError('Bounded manifest required')
    m=strict_json(mraw)
    if type(m) is not dict:raise ValueError('Manifest object required')
    if type(m.get('schemaVersion')) is not int:raise ValueError('Integer schema required')
    if m.get('schemaVersion')==3:
        m=validate_common_v3_bundle(raw,key)
    elif m.get('schemaVersion')==2:
        required={'schemaVersion','bundleId','minAppVersion','model','layoutVersion','identityProtocol','allowedLoaderSha256','legacyRecoverySignedHashes','targetRecoverySignedHash','allowedSourceSignedHashes','main','qualificationSha256'}
        exact(m,required,{'recovery','migration','zigbeeOta'})
        verify_signature(key,entries.get('manifest.sig',b''),mraw)
        if canonical(m)!=mraw or sha(canonical({k:v for k,v in m.items() if k!='bundleId'}))!=m['bundleId']:raise ValueError('Manifest identity mismatch')
        if m['model']!='VIMAR30805' or type(m['layoutVersion']) is not int or m['layoutVersion']!=2 or type(m['identityProtocol']) is not int or m['identityProtocol']!=1:raise ValueError('Unsupported common layout')
        hashes_list(m['allowedLoaderSha256']);hashes_list(m['allowedSourceSignedHashes']);hashes_list(m['legacyRecoverySignedHashes'],empty=True);digest(m['qualificationSha256'])
        if bool(m['legacyRecoverySignedHashes'])!=('migration' in m):raise ValueError('Legacy/migration mismatch')
        expected={'manifest.json','manifest.sig'};metadata={}
        for role in ('main','recovery','migration'):
            if role in m:
                file=role+'.signed.bin';expected.add(file)
                actual=verify_component(entries[file],key,role)
                if canonical(actual)!=canonical(m[role]):raise ValueError('Image metadata mismatch')
                metadata[role]=actual
        if 'recovery' in m and m['recovery']['signedRegionSha256']!=m['targetRecoverySignedHash']:raise ValueError('Recovery identity mismatch')
        if 'zigbeeOta' in m:
            expected.add('main.ota')
            if canonical(verify_zigbee_carrier(entries['main.ota'],entries['main.signed.bin'],key,metadata['main']))!=canonical(m['zigbeeOta']):raise ValueError('Carrier mismatch')
        if set(entries)!=expected:raise ValueError('Unexpected package entry')
    elif m.get('schemaVersion')==1:
        exact(m,{'schemaVersion','bundleId','minAppVersion','device','legacyRecoverySignedHash','targetRecoverySignedHash','allowedSourceSignedHashes','migration','main','provenance'})
        verify_signature(key,entries.get('manifest.sig',b''),mraw)
        if canonical(m)!=mraw or sha(canonical({k:v for k,v in m.items() if k!='bundleId'}))!=m['bundleId']:raise ValueError('Manifest identity mismatch')
        if set(entries)!={'manifest.json','manifest.sig','main.signed.bin','migration.signed.bin'}:raise ValueError('Unexpected legacy entry')
        d=m['device'];exact(d,{'name','ieee','uid','bleAddress'})
        if not isinstance(d['name'],str) or not 1<=len(d['name'].strip())<=128 or not re.fullmatch('[0-9a-f]{16}',d['ieee']) or not re.fullmatch('(?:[0-9A-F]{2}:){5}[0-9A-F]{2}',d['bleAddress']) or type(d['uid']) is not list or len(d['uid'])!=2 or any(not re.fullmatch('[0-9a-f]{8}',x) for x in d['uid']):raise ValueError('Invalid legacy target')
        hashes_list(m['allowedSourceSignedHashes']);digest(m['legacyRecoverySignedHash']);digest(m['targetRecoverySignedHash'])
        exact(m['provenance'],{'deviceDescriptorSha256','otaReleaseSha256','qualificationSha256','migrationInputSha256','migrationReportSha256'})
        for v in m['provenance'].values():digest(v)
        from tools.firmware.package_android_update import signed_metadata
        for role in ('main','migration'):
            meta=signed_metadata(entries[role+'.signed.bin'],role+'.signed.bin',historical=role=='migration')
            if canonical(meta)!=canonical(m[role]):raise ValueError('Legacy signed image mismatch')
    else:raise ValueError('Unsupported package schema')
    if version(app_version)<version(m['minAppVersion']):raise ValueError('A newer updater is required')
    return _admitted(raw,mraw,m)


def inspect_candidate(raw,public_key,app_version='1.0.0'):
    """Separate single-device qualification route, never a normal/fleet release."""
    from tools.firmware.package_common_android_update_v3 import _validate_common_v3_bundle
    key=serialization.load_pem_public_key(public_key) if public_key.startswith(b'-----') else serialization.load_der_public_key(public_key)
    m=_validate_common_v3_bundle(raw,key,expected_purpose='qualification-candidate')
    if version(app_version)<version(m['minAppVersion']):raise ValueError('A newer updater is required')
    return _admitted(raw,canonical(m),m)


def _admitted(raw,mraw,m):
    p=Package(raw,mraw,sha(raw),m['schemaVersion'],m.get('model','VIMAR30805'),m['main']['version'])
    object.__setattr__(p,'_seal',seal('package',p.raw,p.manifest_json,p.digest,p.schema,p.model,p.version));return p
