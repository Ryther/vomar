"""Signed exact-byte Zigbee OTA with durable per-network uncertainty."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
import secrets
import time
from urllib.parse import urlsplit
import urllib.request
from .storage import sha


@dataclass(frozen=True)
class ZigbeeReview:
    token:str
    package_digest:str
    network:str
    ieee:str
    source:str
    birth:int
    expires:float


def carrier_bytes(url,size):
    # This source can be hosted independently of GitHub, but must remain HTTPS.
    # Credentials belong to MQTT's OS store, not public carrier URLs.
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl):
            check_url(newurl);return super().redirect_request(req,fp,code,msg,headers,newurl)
    check_url(url)
    with urllib.request.build_opener(Redirect()).open(url,timeout=20) as r:
        raw=r.read(size+1)
        if len(raw)!=size:raise ValueError('Carrier length mismatch')
        return raw


def check_url(url):
    u=urlsplit(url)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.fragment:raise ValueError('Public HTTPS carrier URL without credentials required')


class ZigbeeEngine:
    def __init__(self,store,bridge,scheduler,on_event=lambda _:None,fetch=carrier_bytes):
        self.store=store;self.bridge=bridge;self.scheduler=scheduler;self.on_event=on_event;self.fetch=fetch;self.reviews={};self.consents={}
    def held(self,network):return any(s['binding'].get('network')==network and s['uncertain'] for s in self.store.sessions())
    async def inspect(self,package,network,ieee,source):
        package.assert_verified()
        meta=package.manifest.get('zigbeeOta')
        if not meta or package.manifest.get('purpose'):raise ValueError('A normal signed release with an OTA carrier is required')
        if self.held(network):raise ValueError('An earlier submitted update is uncertain on this network; explicitly reconcile its status')
        raw=await asyncio.to_thread(self.fetch,source,meta['size'])
        if sha(raw)!=meta['fileSha256'] or raw!=package.entries()['main.ota']:raise ValueError('HTTPS bytes differ from the exact signed carrier')
        self.bridge.target(network,ieee)
        check=await self.bridge.request(network,ieee,'check',source)
        if check.get('update_available') is not True or check.get('source')!=source:raise ValueError('Bridge did not confirm the exact selected carrier source')
        await self.bridge.verify_recovery(network,ieee,package.manifest['targetRecoverySignedHash'])
        r=ZigbeeReview(secrets.token_hex(24),package.digest,network,ieee,source,self.bridge.birth,time.monotonic()+300);self.reviews[r.token]=r;return r
    def approve(self,r):
        if self.reviews.get(r.token)!=r or r.expires<time.monotonic():raise ValueError('Zigbee review expired')
        c=secrets.token_hex(32);self.consents[c]=r.token;return c
    async def execute(self,package,r,consent):
        package.assert_verified()
        if self.consents.pop(consent,None)!=r.token or self.reviews.pop(r.token,None)!=r or r.expires<time.monotonic() or package.digest!=r.package_digest:raise ValueError('Fresh exact Zigbee approval required')
        async def operation():
            if self.held(r.network) or self.bridge.birth!=r.birth:raise ValueError('Network state changed after review')
            await self.bridge.verify_recovery(r.network,r.ieee,package.manifest['targetRecoverySignedHash'])
            meta=package.manifest['zigbeeOta'];session=self.store.begin({'operation':'zigbee-update','network':r.network,'ieee':r.ieee,'package':package.digest,'source':r.source,'version':package.version,'fileVersion':meta['fileVersion']})
            self.store.record(session,'mqtt-update-intent')
            try:
                response=await self.bridge.request(r.network,r.ieee,'update',r.source,timeout=7200)
                to=response.get('to')
                if type(to) is not dict or type(to.get('file_version')) is not int or to['file_version']!=meta['fileVersion']:raise ValueError('Bridge completed another or unknown firmware version')
                if to.get('software_build_id')==package.version:
                    self.store.record(session,'verified');return session
                before=time.monotonic();deadline=before+180
                while time.monotonic()<deadline:
                    observation=self.bridge.observations.get((r.network,r.ieee))
                    if observation and not observation['retained'] and observation['at']>before and observation['birth']==r.birth:
                        data=observation['value'];installed=data.get('update',{}).get('installed_version')
                        if data.get('software_build_id',data.get('software_build'))==package.version and installed in (None,meta['fileVersion']):self.store.record(session,'verified');return session
                    await asyncio.sleep(.2)
                raise TimeoutError('Transfer acknowledged; device return is not verified')
            except BaseException:
                self.store.record(session,'interrupted');raise
        return await self.scheduler.run('network:'+r.network,operation)
    async def reconcile(self,session):
        s=next((s for s in self.store.sessions() if s['id']==session),None)
        if not s or s['binding'].get('operation')!='zigbee-update':raise ValueError('Unknown Zigbee session')
        b=s['binding'];before=time.monotonic();await self.bridge.request(b['network'],b['ieee'],'check')
        deadline=before+5
        while time.monotonic()<deadline:
            o=self.bridge.observations.get((b['network'],b['ieee']))
            if o and not o['retained'] and o['at']>before and o['birth']==self.bridge.birth:
                update=o['value'].get('update',{})
                if update.get('state') in ('idle','available') and type(update.get('installed_version')) is int:
                    if update['installed_version']==b['fileVersion']:
                        self.store.record(session,'verified');return {'state':'verified'}
                    self.store.record(session,'operator-confirmed',{'evidence':'Fresh correlated idle state with another version; no update resubmitted'});return {'state':'paused','version':update['installed_version']}
            await asyncio.sleep(.1)
        raise ValueError('No fresh correlated idle evidence; network remains held')
