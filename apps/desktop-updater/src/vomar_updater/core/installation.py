"""Bounded first-install, explicit repair and start transactions.

The wire port has no UICR-write/mass-erase method. A failed host transaction
preserves HALT and uncertainty; returning from this engine never starts a CPU.
"""
from __future__ import annotations
from dataclasses import dataclass
import datetime as dt
import hashlib
import io
import json
import secrets
import struct
import time
import zipfile
import zlib
from .packages import read_zip,strict_json,canonical
from .admission import seal,require

FLASH=0x100000;PAGE=4096;ANCHOR=0xb000;COMMIT_OFFSET=252;COMMIT=0xa60c17ed
REGIONS={'flash.bin':(0,FLASH),'ficr.bin':(0x10000000,PAGE),'uicr.bin':(0x10001000,PAGE)}


def sha(raw):return hashlib.sha256(raw).hexdigest()
def word(raw,offset):return struct.unpack_from('<I',raw,offset)[0]


def identity(ficr):
    if len(ficr)!=PAGE or any(word(ficr,at)!=v for at,v in ((0x10,4096),(0x14,256),(0x100,0x52840),(0x10c,256),(0x110,1024))):raise ValueError('Unsupported nRF52840 geometry')
    variant=word(ficr,0x104)
    if not 1<=variant<=0xfffffffe:raise ValueError('Invalid part variant')
    return word(ficr,0x60),word(ficr,0x64),variant


def watchdog(profile,policy=None):
    if type(profile) is not dict or set(profile)!={'runStatus','config','crv','rren'} or any(type(v) is not int for v in profile.values()):raise ValueError('Exact watchdog observation required')
    r,c,v,e=(profile[k] for k in ('runStatus','config','crv','rren'))
    if r not in (0,1) or not 0<=c<=0xffffffff or c&~9 or not 0<=v<=0xffffffff or not 0<=e<=255:raise ValueError('Malformed watchdog profile')
    if r and (c&8 or not e or v+1>60*32768):raise ValueError('Active watchdog must pause while halted with bounded interval')
    if r and policy!='paused-reset-before-main-v1':raise ValueError('Active watchdog requires a signed reset handoff capability')


@dataclass(frozen=True)
class Original:
    raw:bytes
    flash:bytes
    ficr:bytes
    uicr:bytes
    identity:tuple[int,int,int]
    @property
    def digest(self):return sha(self.raw)
    def require_fresh(self):
        if self.flash[0xb0000:0xef000]!=b'\xff'*0x3f000 or self.flash[ANCHOR:ANCHOR+4]==b'VAR1':raise ValueError('Original scratch/anchor is incompatible; use the preserved original and explicit repair')


def verify_original(raw):
    limits={**{n:s for n,(_,s) in REGIONS.items()},'manifest.json':65536,'README.txt':8192}
    entries=read_zip(raw,limits=limits,max_size=2*1024*1024)
    if set(entries)!=set(limits):raise ValueError('Original archive member set mismatch')
    m=strict_json(entries['manifest.json'])
    if type(m) is not dict or type(m.get('schema')) is not int:raise ValueError('Exact original schema required')
    ficr=entries['ficr.bin'];flash=entries['flash.bin'];uicr=entries['uicr.bin'];uid=identity(ficr)
    if any(len(entries[n])!=s for n,(_,s) in REGIONS.items()) or not entries['README.txt'].decode('utf-8').strip():raise ValueError('Original region size mismatch')
    stack=word(flash,0);reset=word(flash,4)
    if not 0x20000000<stack<=0x20040000 or stack%8 or not reset&1 or not 8<=reset&~1<FLASH:raise ValueError('Original vector geometry mismatch')
    if m.get('schema')==2:
        if set(m)!={'schema','type','target','regions','startedAt','verifiedAt','acquisition','provenance'} or m['type']!='nrf52840-openocd-halted-backup-v1':raise ValueError('Unsupported OpenOCD original format')
        if type(m['target'].get('variant')) is not int or m['target'].get('commercialModelVerified') is not False or m['target']!={'uid':[f'{uid[0]:08x}',f'{uid[1]:08x}'],'variant':uid[2],'part':0x52840,'commercialModelVerified':False}:raise ValueError('Original FICR identity mismatch')
        a=m['acquisition']
        if set(a)!={'cpuHalted','byteExactDoubleRead','flashWrite','uicrWrite','watchdog'} or any(a[k] is not v for k,v in [('cpuHalted',True),('byteExactDoubleRead',True),('flashWrite',False),('uicrWrite',False)]):raise ValueError('Original acquisition contract mismatch')
        profile=a['watchdog'];watchdog(profile,'paused-reset-before-main-v1')
        p=m['provenance']
        if set(p)!={'transport','version','serial'} or p['transport']!='openocd' or any(not isinstance(p[k],str) or not 1<=len(p[k])<=1024 for k in ('version','serial')):raise ValueError('Invalid acquisition provenance')
    elif m.get('schema')==1:
        halted=m.get('type')=='nrf52840-quiescent-first-install-backup'
        fields={'schema','type','target','byteExactDoubleRead','startedAt','verifiedAt','snapshotAtomic','protocol','scope','provenance','regions'}|({'acquisition'} if halted else set())
        if set(m)!=fields or m['type'] not in ('nrf52840-quiescent-first-install-backup','nrf52840-read-only-double-backup') or m['byteExactDoubleRead'] is not True or m['snapshotAtomic'] is not False:raise ValueError('Original acquisition contract mismatch')
        if m['protocol']!={'id':'jlink-raw-swd-ap0-halted-backup-v1' if halted else 'jlink-raw-swd-ap0-read-v1','swdClockKhz':100,'maxBlockBytes':512,'tarBoundaryBytes':1024,'independentBlockSentinels':True}:raise ValueError('Original protocol mismatch')
        reset=False
        if halted:
            a=m['acquisition']
            if not {'cpuHalted','method','originalCpuControl'}<=set(a) or set(a)-{'cpuHalted','method','originalCpuControl','watchdog'} or a['cpuHalted'] is not True or a['method'] not in ('debug-halt','reset-vector-catch') or type(a['originalCpuControl']) is not int or a['originalCpuControl'] not in (0,1,3):raise ValueError('Original halt provenance mismatch')
            reset=a['method']=='reset-vector-catch'
            if 'watchdog' in a:watchdog(a['watchdog'],'paused-reset-before-main-v1')
        expected={'haltAttempted':halted,'resetAttempted':reset,'eraseAttempted':False,'memoryWrite':halted,'flashed':False,'targetSupplyChanged':False,'debugPortConfigured':True,'restorationVerified':False}
        if halted:expected.update(flashWrite=False,uicrWrite=False)
        if m['scope']!=expected or any(type(x) is not bool for x in m['scope'].values()):raise ValueError('Original scope mismatch')
        p=m['provenance']
        if set(p)!={'appVersion','probeFirmware','usbVendorId','usbProductId','interfaceId','inputEndpoint','outputEndpoint','targetMillivolts'} or p['usbVendorId']!=0x1366 or p['usbProductId']!=0x1060 or not 1700<=p['targetMillivolts']<=3600 or not 0x81<=p['inputEndpoint']<=0x8f or not 1<=p['outputEndpoint']<=15:raise ValueError('Original USB provenance mismatch')
        if any(type(p[k]) is not int for k in ('usbVendorId','usbProductId','interfaceId','inputEndpoint','outputEndpoint','targetMillivolts')) or not 0<=p['interfaceId']<=2147483647 or any(not isinstance(p[k],str) or not 1<=len(p[k].strip())<=limit for k,limit in (('appVersion',128),('probeFirmware',1024))):raise ValueError('Original provenance scalar types mismatch')
        recognized=[]
        for entry in [dict(id='vimar-30805-mesh',model='VIMAR30805',radio='mesh',offset=0x26000,size=213012,sha256='8c0408c49fe3e35758a69e511faa154c2f1237512e1c1bfdf1061221db53f927'),dict(id='vimar-30805-zigbee',model='VIMAR30805',radio='zigbee',offset=0x26000,size=343988,sha256='710f788a02eca3985d5826efacf47cef8d8fa29dde4684815c25c8c9a79690d5')]:
            if sha(flash[entry['offset']:entry['offset']+entry['size']])==entry['sha256']:recognized.append(entry)
        target={'chip':'nRF52840','part':'0x00052840','uid':[f'0x{uid[0]:08x}',f'0x{uid[1]:08x}'],'identitySource':'live FICR before/after both passes','commercialModelVerified':False,'model':'stock application recognized; hardware model unverified' if recognized else 'unknown nRF52840 device'}
        if recognized:target.update(applicationDigestMatched=True,firmwareModel=','.join(dict.fromkeys(e['model'] for e in recognized)),recognizedApplications=recognized)
        if m['target']!=target or m['target']['commercialModelVerified'] is not False:raise ValueError('Original target mismatch')
    else:raise ValueError('Unsupported original archive schema')
    for t in ('startedAt','verifiedAt'):
        import re
        if not isinstance(m[t],str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z',m[t]):raise ValueError('UTC acquisition time required')
    if dt.datetime.fromisoformat(m['verifiedAt'])<dt.datetime.fromisoformat(m['startedAt']):raise ValueError('Acquisition time reversal')
    expected=[{'file':n,'start':f'0x{at:08x}','size':size,'sha256':sha(entries[n]),'verifiedCopies':2} for n,(at,size) in REGIONS.items()]
    if m['regions']!=expected:raise ValueError('Original region hashes mismatch')
    return Original(raw,flash,ficr,uicr,uid)


def capture_original(probe,check=lambda:None):
    if not probe.halted:raise ValueError('Explicitly approved exclusive halted lease required')
    probe.capture_ready()
    started=dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00','Z');passes=[];before=probe.identity();profile=probe.watchdog()
    watchdog(profile,'paused-reset-before-main-v1')
    for _ in range(2):
        regions={}
        for name,(start,size) in REGIONS.items():
            data=bytearray()
            for offset in range(0,size,512):
                check();probe.check(before);data.extend(probe.read(start+offset,min(512,size-offset)))
            if len(data)!=size:raise ValueError('Short original read')
            regions[name]=bytes(data)
        probe.check(before);passes.append(regions)
    if passes[0]!=passes[1]:raise ValueError('Independent acquisition passes differ')
    entries=passes[0];uid=identity(entries['ficr.bin'])
    m={'schema':2,'type':'nrf52840-openocd-halted-backup-v1','target':{'uid':[f'{uid[0]:08x}',f'{uid[1]:08x}'],'variant':uid[2],'part':0x52840,'commercialModelVerified':False},'startedAt':started,'verifiedAt':dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00','Z'),'acquisition':{'cpuHalted':True,'byteExactDoubleRead':True,'flashWrite':False,'uicrWrite':False,'watchdog':profile},'provenance':{'transport':'openocd','version':probe.version,'serial':probe.serial},'regions':[{'file':n,'start':f'0x{at:08x}','size':s,'sha256':sha(entries[n]),'verifiedCopies':2} for n,(at,s) in REGIONS.items()]}
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for n,b in {**entries,'manifest.json':canonical(m),'README.txt':b'Original double-read while halted. No FLASH or UICR mutation. Producer-reported OpenOCD provenance; no hardware qualification.\n'}.items():z.writestr(n,b)
    return verify_original(out.getvalue())


@dataclass(frozen=True)
class InstallPlan:
    original:Original
    package_digest:str
    family:str
    body:bytes
    final:bytes
    watchdog_policy:str|None
    _seal:bytes=b''
    def assert_verified(self):require(self._seal,seal("install",self.original.raw,self.original.flash,self.original.ficr,self.original.uicr,self.original.identity,self.package_digest,self.family,self.body,self.final,self.watchdog_policy))
    @property
    def binding(self):return {'target':list(self.original.identity),'original':self.original.digest,'package':self.package_digest,'family':self.family,'body':sha(self.body),'installed':sha(self.final)}


def prepare_install(original,package):
    package.assert_verified()
    if verify_original(original.raw)!=original:raise ValueError('Original material differs from its verified archive')
    original.require_fresh();m=package.manifest
    if package.schema!=3 or 'firstInstall' not in m:raise ValueError('Signed schema3 first-install authority required')
    entries=package.entries();descriptor=strict_json(entries['first-install.json']);loader=entries['loader.bin']
    table=b''.join(hashlib.sha256(original.flash[i:i+PAGE]).digest() for i in range(0,FLASH,PAGE))
    anchor=bytearray(b'\xff'*PAGE);anchor[:8]=b'VAR1\x01\x00\x00\x01'
    u0,u1,variant=original.identity
    for at,v in ((8,1),(12,2),(16,0x52840),(20,variant),(24,u0),(28,u1),(32,FLASH),(36,PAGE),(40,0x40000),(44,PAGE),(48,8192)):struct.pack_into('<I',anchor,at,v)
    anchor[52:64]=b'VIMAR30805\0\0';anchor[64:96]=hashlib.sha256(original.flash).digest();anchor[96:128]=hashlib.sha256(original.uicr).digest();anchor[128:160]=hashlib.sha256(table).digest()
    struct.pack_into('<I',anchor,248,zlib.crc32(anchor[:248]));struct.pack_into('<I',anchor,COMMIT_OFFSET,COMMIT)
    final=bytearray(b'\xff'*FLASH);final[:0xc000]=loader;final[ANCHOR:0xc000]=anchor
    for role,start in (('main',0xc000),('recovery',0xb0000)):
        blob=package.image(role);final[start:start+len(blob)]=blob
    body=bytearray(final);body[ANCHOR+COMMIT_OFFSET:ANCHOR+COMMIT_OFFSET+4]=b'\xff'*4
    plan=InstallPlan(original,package.digest,descriptor['loaderContracts'][0]['sha256'],bytes(body),bytes(final),descriptor.get('watchdogHandoff'))
    object.__setattr__(plan,'_seal',seal('install',plan.original.raw,plan.original.flash,plan.original.ficr,plan.original.uicr,plan.original.identity,plan.package_digest,plan.family,plan.body,plan.final,plan.watchdog_policy));return plan


@dataclass(frozen=True)
class InstallReview:
    token:str
    binding_json:str
    snapshot:str
    generation:str
    export_path:str
    resume_session:str|None
    journal_head:str|None
    start:bool


class InstallEngine:
    def __init__(self,store,on_event=lambda _:None):self.store=store;self.on_event=on_event;self._reviews={};self._consents={};self.stopped=False
    def stop(self):self.stopped=True;self._reviews.clear();self._consents.clear()
    def check(self):
        if self.stopped:raise InterruptedError('Stopped by operator; target remains halted')
    def _guard(self,plan,probe):
        self.check();probe.check(plan.original.identity)
        if not probe.halted or probe.read(0x10001000,PAGE)!=plan.original.uicr or probe.read(0x10000000,PAGE)!=plan.original.ficr:raise ValueError('Live protected identity or UICR changed')
        watchdog(probe.watchdog(),plan.watchdog_policy)
    def review(self,plan,probe,export_path,*,resume_session=None,start=False):
        plan.assert_verified();self.stopped=False;self._guard(plan,probe)
        if not self.store.reopen_receipt(plan.original.digest,export_path):raise ValueError('Reopen the exact exported protected original first')
        current=probe.read(0,FLASH)
        if len(current)!=FLASH:raise ValueError('Incomplete FLASH read')
        head=None
        if resume_session:
            old=next((s for s in self.store.sessions() if s['id']==resume_session),None)
            if old is None or old['binding']!=plan.binding:raise ValueError('Repair requires the same original/release/target binding')
            events=self.store.events(resume_session);head=sha(canonical(events))
            receipts=[e for e in events if e['phase']=='original-export-reopened']
            if len(receipts)!=1 or receipts[0]['detail'].get('digest')!=plan.original.digest:raise ValueError('Initial protected-original export receipt is missing or differs')
            if any(s['binding']==plan.binding and any(e['phase']=='start-acknowledged' for e in self.store.events(s['id'])) for s in self.store.sessions()):raise ValueError('A start was acknowledged; initial-install repair is no longer authorized')
            frontier=max([e['detail'].get('address',-1) for e in events if e['phase']=='erase-intent'] or [-1])
            for at in range(0,FLASH,PAGE):
                if at>frontier and current[at:at+PAGE]!=plan.original.flash[at:at+PAGE]:raise ValueError('Unissued page differs from protected original')
        elif not start and current!=plan.original.flash:raise ValueError('Live FLASH differs from original; explicit repair required')
        if start and current!=plan.final:raise ValueError('Complete installed image must be verified before explicit start')
        r=InstallReview(secrets.token_hex(24),json.dumps(plan.binding,sort_keys=True),sha(current),probe.generation,str(export_path),resume_session,head,start)
        self._reviews[r.token]=(r,time.monotonic()+300);return r
    def approve(self,review):
        if self._reviews.get(review.token,(None,0))[0]!=review or self._reviews[review.token][1]<time.monotonic():raise ValueError('Installation review expired')
        c=secrets.token_hex(32);self._consents[c]=(review.token,time.monotonic()+120);return c
    def execute(self,plan,probe,review,consent):
        plan.assert_verified();self.stopped=False;c=self._consents.pop(consent,None)
        if c is None or c[0]!=review.token or c[1]<time.monotonic() or self._reviews.pop(review.token,None) is None:raise ValueError('Fresh single-attempt installation consent required')
        if json.dumps(plan.binding,sort_keys=True)!=review.binding_json or probe.generation!=review.generation:raise ValueError('Reviewed lease/binding changed')
        self._guard(plan,probe)
        if not self.store.reopen_receipt(plan.original.digest,review.export_path):raise ValueError('Export changed after review')
        current=probe.read(0,FLASH)
        if sha(current)!=review.snapshot:raise ValueError('FLASH changed after review')
        session=review.resume_session
        if session:
            if sha(canonical(self.store.events(session)))!=review.journal_head:raise ValueError('Repair journal changed after review')
        else:
            if any(s['binding']==plan.binding for s in self.store.sessions()) and not review.start:raise ValueError('Existing transaction requires explicit repair review')
            session=self.store.begin(plan.binding)
            if not review.start:self.store.record(session,'original-export-reopened',{'digest':plan.original.digest,'path':str(__import__('pathlib').Path(review.export_path).absolute())})
        def record(phase,address=None):
            self.check();self.store.record(session,phase,{} if address is None else {'address':address});self.on_event({'session':session,'phase':phase,'address':address})
        try:
            if review.start:
                if current!=plan.final:raise ValueError('Installed bytes changed before start')
                record('start-intent');probe.start();record('start-acknowledged');record('await-operator');return session
            if current!=plan.body and current!=plan.final:
                for at in range(0,FLASH,PAGE):
                    self._guard(plan,probe);wanted=plan.body[at:at+PAGE]
                    record('erase-intent',at);probe.erase_page(at,plan.original.identity)
                    for offset in range(0,PAGE,256):
                        batch=wanted[offset:offset+256]
                        if batch!=b'\xff'*len(batch):
                            record('write-intent',at+offset);probe.program(at+offset,batch,plan.original.identity)
                    if probe.read(at,PAGE)!=wanted:raise ValueError('FLASH page readback mismatch')
            if probe.read(0,FLASH)!=plan.final:
                if probe.read(0,FLASH)!=plan.body:raise ValueError('Complete body verification failed')
                self._guard(plan,probe);record('commit-intent',ANCHOR+COMMIT_OFFSET)
                probe.program(ANCHOR+COMMIT_OFFSET,struct.pack('<I',COMMIT),plan.original.identity)
            self._guard(plan,probe)
            if probe.read(0,FLASH)!=plan.final:raise ValueError('Final complete image verification failed')
            record('verified');return session
        except BaseException:
            self.store.record(session,'interrupted');raise
        # No finally CPU release, reset, retry, erase or UICR operation.
