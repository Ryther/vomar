"""Shared asynchronous operation engine. Presentations never acquire write authority."""
from __future__ import annotations
import asyncio
from dataclasses import asdict, dataclass
import hashlib
import json
import secrets
import time
from typing import Protocol
from .packages import Package
from .storage import Store

COMMON='common-code44k-anchor-v1'
LEGACY='legacy-full48k-sha256'


@dataclass(frozen=True)
class Identity:
    protocol:int
    model:str
    layout:int
    uid:tuple[str,str]
    loader_kind:str
    loader_sha256:str
    anchor_sha256:str|None=None
    def validate(self):
        import re
        if self.model!='VIMAR30805' or self.layout!=2 or len(self.uid)!=2 or any(not re.fullmatch('[0-9a-f]{8}',x) for x in self.uid):raise ValueError('Unsupported runtime identity')
        if self.protocol not in (1,2) or not re.fullmatch('[0-9a-f]{64}',self.loader_sha256):raise ValueError('Invalid loader identity')
        if self.loader_kind not in (COMMON,LEGACY) or (self.protocol==1 and self.loader_kind!=LEGACY):raise ValueError('Invalid typed loader')
        if self.loader_kind==COMMON:
            if self.protocol!=2 or not isinstance(self.anchor_sha256,str) or not re.fullmatch('[0-9a-f]{64}',self.anchor_sha256):raise ValueError('Common loader requires anchor identity')
        elif self.anchor_sha256 is not None:raise ValueError('Legacy loader cannot claim an anchor')


@dataclass(frozen=True)
class Preview:
    token:str
    package_digest:str
    target:str
    identity:Identity
    operation:str
    observed_json:str
    original_digest:str|None
    @property
    def fingerprint(self):return hashlib.sha256(json.dumps(asdict(self),sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class Event:
    phase:str
    message:str
    completed:int=0
    total:int=0
    session:str|None=None


class BlePort(Protocol):
    authenticated:bool
    async def connect(self,target:str):...
    async def identity(self)->Identity:...
    async def images(self)->dict:...
    async def upload(self,raw:bytes,progress):...
    async def reset(self)->bool:...
    async def migration(self,primary:str,recovery:str)->bool:...
    async def close(self):...


class Engine:
    def __init__(self,store:Store,ble:BlePort,*,lease=None,on_event=None):
        self.store=store;self.ble=ble;self.lease=lease or asyncio.Lock();self.on_event=on_event or (lambda _:None)
        self._previews={};self._consents={};self._stop=asyncio.Event()
    def stop(self):self._stop.set()
    def check(self):
        if self._stop.is_set():raise asyncio.CancelledError('Stopped by operator')
    def emit(self,phase,message,session=None,completed=0,total=0):self.on_event(Event(phase,message,completed,total,session))
    @staticmethod
    def compatible(package,identity):
        identity.validate();m=package.manifest
        if package.schema==1:
            if list(identity.uid)!=m['device']['uid']:raise ValueError('Device-bound package target mismatch')
        elif package.schema==2:
            if identity.protocol!=1 or identity.loader_sha256 not in m['allowedLoaderSha256']:raise ValueError('Loader not authorized')
        elif {'kind':identity.loader_kind,'sha256':identity.loader_sha256} not in m['loaderContracts']:raise ValueError('Typed loader not authorized')
    @staticmethod
    def decision(package,images):
        m=package.manifest;r=images.get('recovery');p=images.get('primary')
        legacy=m.get('legacyRecoverySignedHashes',[m.get('legacyRecoverySignedHash')])
        if not r or not r.get('active') or not r.get('bootable') or r.get('hash') not in legacy+[m['targetRecoverySignedHash']]:raise ValueError('Unexpected active recovery')
        if not p or not p.get('bootable'):raise ValueError('Primary is absent/unbootable; explicit interrupted-session repair required')
        h=p.get('hash')
        if r['hash'] in legacy:
            if 'migration' not in m:raise ValueError('No authorized migration image')
            if h==m['migration']['signedRegionSha256']:return 'migration-reset'
            if h in m['allowedSourceSignedHashes']:return 'upload-migration'
        else:
            if h==m['main']['signedRegionSha256']:return 'final-reset'
            if h in m['allowedSourceSignedHashes'] or h==m.get('migration',{}).get('signedRegionSha256'):return 'upload-main'
        raise ValueError('Unexpected primary image')
    async def _live(self,package,expected=None):
        self.check()
        i=await self.ble.identity()
        if not self.ble.authenticated:raise ValueError('Authenticated Bluetooth bond required; OS security is unavailable')
        self.compatible(package,i)
        if expected is not None and i!=expected:raise ValueError('Live target/loader/anchor changed; preview again')
        return i
    async def inspect(self,package:Package,target:str,operation='update',original_digest=None):
        if operation not in ('update','trial'):raise ValueError('Unsupported BLE operation')
        async with self.lease:
            self._stop.clear()
            try:
                await self.ble.connect(target);i=await self._live(package);images=await self.ble.images();self.decision(package,images)
                p=Preview(secrets.token_hex(24),package.digest,target,i,operation,json.dumps(images,sort_keys=True),original_digest)
                self._previews[p.token]=(p,time.monotonic()+300);return p
            finally:await self.ble.close()
    def approve(self,preview):
        if self._previews.get(preview.token,(None,0))[0]!=preview or self._previews[preview.token][1]<time.monotonic():raise ValueError('Preview expired; inspect again')
        token=secrets.token_hex(32);self._consents[token]=(preview.fingerprint,time.monotonic()+120);return token
    def _claim(self,preview,consent):
        record=self._consents.pop(consent,None)
        if record is None or record[0]!=preview.fingerprint or record[1]<time.monotonic():raise ValueError('Fresh operation-specific consent required')
        self._previews.pop(preview.token,None)
    async def execute(self,package,preview,consent):
        self._claim(preview,consent)
        if package.digest!=preview.package_digest:raise ValueError('Package changed')
        if self.lease.locked():raise ValueError('Bluetooth is busy')
        async with self.lease:
            self._stop.clear();session=self.store.begin({'package':package.digest,'target':preview.target,'identity':asdict(preview.identity),'operation':preview.operation,'original':preview.original_digest})
            self.store.put(package.raw,'package');self.emit('connecting','Connecting to reviewed device',session)
            try:
                await self.ble.connect(preview.target);await self._live(package,preview.identity)
                images=await self.ble.images()
                if json.dumps(images,sort_keys=True)!=preview.observed_json:raise ValueError('Images changed after review')
                for _ in range(4):
                    await self._live(package,preview.identity);action=self.decision(package,images)
                    self.check();self.store.record(session,action+'-intent',{'images':images})
                    self.emit(action,action.replace('-',' ').capitalize(),session)
                    if action.startswith('upload-'):
                        role=action.split('-')[1];raw=package.image(role)
                        async def progress(offset):
                            self.check()
                            if type(offset) is not int or not 0<=offset<=len(raw):raise ValueError('Invalid upload acknowledgment')
                            self.store.record(session,'upload-progress',{'role':role,'offset':offset});self.emit('upload',f'Uploading {role}',session,offset,len(raw))
                        await self.ble.upload(raw,progress);await self._live(package,preview.identity)
                        observed=await self.ble.images()
                        if observed.get('primary',{}).get('hash')!=package.manifest[role]['signedRegionSha256'] or not observed['primary'].get('bootable') or observed['recovery']!=images['recovery']:raise ValueError('Uploaded image readback mismatch')
                        images=observed;continue
                    await self._live(package,preview.identity)
                    if await self.ble.images()!=images:raise ValueError('Images changed before reset')
                    if action=='migration-reset':
                        ack=await self.ble.migration(package.manifest['migration']['signedRegionSha256'],images['recovery']['hash'])
                        self.store.record(session,'await-reconnect',{'acknowledged':ack})
                        self.emit('await-operator','Migration requested. Inspect again after recovery reconnects.',session);return session
                    ack=await self.ble.reset();self.store.record(session,'await-operator',{'acknowledged':ack})
                    self.emit('await-operator','Reset requested. Verify the dimmer physically; radio acknowledgment does not prove success.',session);return session
                raise ValueError('Operation step bound exceeded')
            except BaseException:
                self.store.record(session,'interrupted');self.emit('interrupted','Operation interrupted. Review preserved session before another attempt.',session);raise
            finally:await self.ble.close()
    async def resume(self,session,package,fresh_preview,consent):
        prior=next((s for s in self.store.sessions() if s['id']==session),None)
        if prior is None:raise ValueError('Unknown interrupted session')
        b=prior['binding']
        if b['package']!=package.digest or b['target']!=fresh_preview.target or b['identity']!=json.loads(json.dumps(asdict(fresh_preview.identity))) or b.get('original')!=fresh_preview.original_digest:raise ValueError('Resume binding differs')
        return await self.execute(package,fresh_preview,consent)
