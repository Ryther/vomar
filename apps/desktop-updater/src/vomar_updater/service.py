"""Presentation-neutral application owner. Construct on the owning event loop/thread."""
from __future__ import annotations
import asyncio
from dataclasses import asdict
from importlib.resources import files
import json
from pathlib import Path
import secrets
from platformdirs import user_data_path
from .core.engine import Engine
from .core.fleet import Registry,Scheduler,Broker,Network,Batches
from .core.installation import InstallEngine,capture_original,verify_original,prepare_install
from .core.packages import inspect_package
from .core.storage import Store
from .adapters.smp import BleakSmp
from .adapters.openocd import OpenOcdProbe
from .adapters.credentials import Credentials
from .adapters.mqtt import MqttBridge
from .adapters import releases


class Service:
    def __init__(self,state=None,on_event=lambda _:None):
        self.store=Store(state or user_data_path('Vomar','OpenVimar'));self.registry=Registry(self.store);self.batches=Batches(self.store);self.scheduler=Scheduler();self.batch_ble=asyncio.Lock()
        self.candidate=None;self.zigbee=None;self.on_event=on_event;self.ble=BleakSmp();self.engine=Engine(self.store,self.ble,lease=self.scheduler.ble,on_event=lambda e:on_event(asdict(e)))
        self.installer=InstallEngine(self.store,on_event);self.package=None;self.probe=None;self.original=None;self.export_path=None;self.plan=None;self.reviews={};self.mqtt=None
        self.anchor=files('vomar_updater').joinpath('resources/firmware-public.der').read_bytes()
    def stop(self):self.engine.stop();self.installer.stop();self.scheduler.stop();self.reviews.clear()
    def _review(self,kind,review,summary,challenge):
        token=secrets.token_hex(24);self.reviews[token]=(kind,review)
        return {'review':token,'operation':kind,'summary':summary,'challenge':challenge,'message':'Review this exact operation. Approval expires and is never restored after restart.'}
    def need_package(self):
        if self.package is None:raise ValueError('Choose and verify a signed firmware ZIP first')
        return self.package
    async def dispatch(self,action,args=None):
        a=args or {}
        if action=='releases.inspect':
            raw=Path(a['path']).read_bytes();self.package=inspect_package(raw,self.anchor);self.store.put(raw,'package')
            return {'digest':self.package.digest,'version':self.package.version,'schema':self.package.schema,'model':self.package.model}
        if action=='releases.latest':
            metadata,assets=await asyncio.to_thread(releases.latest,a.get('repository','Ryther/vomar'))
            raw=await asyncio.to_thread(releases.acquire,assets['firmware-common']);self.package=inspect_package(raw,self.anchor)
            self.store.put(raw,'package');self.store.setting('selected-release',self.package.digest);self.store.setting('release-assets',assets)
            return {'distribution':metadata['distributionVersion'],'firmware':self.package.version,'digest':self.package.digest}
        if action=='trial.inspect':
            from .core.packages import inspect_candidate
            self.candidate=inspect_candidate(Path(a['path']).read_bytes(),self.anchor)
            return {'candidate':self.candidate.digest,'version':self.candidate.version,'physicalQualification':False}
        if action in ('trial.preview','updates.prepare-preview'):
            p=self.candidate if action=='trial.preview' else self.need_package()
            if p is None:raise ValueError('Choose a candidate through the separate Bluetooth trial tool')
            r=await self.engine.inspect(p,a['target'],operation='trial' if action=='trial.preview' else 'bootstrap')
            return self._review('trial' if action=='trial.preview' else 'prepare',r,asdict(r),r.identity.uid[-1] if r.identity else r.target[-8:])
        if action=='devices.list':return self.registry.list()
        if action=='devices.import':return {'imported':self.registry.import_records(Path(a['path']).read_bytes())}
        if action=='devices.save':
            r={'id':a.get('id') or secrets.token_hex(8),'name':a['name'],'room':a.get('room',''),'ble':a.get('target',''),'ieee':a.get('ieee',''),'network':a.get('network','')};self.registry.save(r);return r
        if action=='devices.remove':self.registry.remove(a['id']);return {'removed':a['id']}
        if action=='devices.scan':
            async with self.scheduler.ble:return await self.ble.scan()
        if action=='fleet.list':return self.batches.list()
        if action=='fleet.preview':
            selected=a.get('ids',a.get('id','').split(','));rows=[r for r in self.registry.list() if r['id'] in selected]
            if not rows or len(rows)!=len(set(selected)):raise ValueError('Choose distinct saved devices for the batch')
            package=self.need_package();reviews=[]
            for r in rows:
                if not r['ble']:raise ValueError('This Bluetooth batch contains a device without a nearby target; choose an explicit Zigbee route for network jobs')
                reviews.append(await self.engine.inspect(package,r['ble']))
            group=self.batches.create(package.digest,[r['id'] for r in rows],a.get('mode','sequential'))
            return self._review('fleet',(group,reviews),{'batch':group['id'],'package':package.digest,'devices':[{'name':row['name'],'room':row['room'],'identity':asdict(r.identity)} for row,r in zip(rows,reviews)]},group['id'][-8:])
        if action=='sessions.list':return self.store.sessions()
        if action=='sessions.details':return self.store.events(a['session'])
        if action=='sessions.confirm':
            session=next((s for s in self.store.sessions() if s['id']==a['session']),None)
            if not session or session['phase']!='await-operator':raise ValueError('Only a pending physical verification can be confirmed')
            return self._review('operator-confirm',a['session'],{'session':a['session'],'evidence':'Operator confirms actual dimmer operation; this is not fleet firmware qualification'},a['session'][-8:])
        if action=='updates.preview':
            p=await self.engine.inspect(self.need_package(),a['target'])
            return self._review('update',p,asdict(p),p.identity.uid[-1])
        if action=='updates.resume-preview':
            prior=next((s for s in self.store.sessions() if s['id']==a['session']),None)
            if prior is None:raise ValueError('Choose an interrupted Bluetooth session')
            r=await self.engine.inspect(self.need_package(),prior['binding']['target'],resume_session=prior['id'])
            return self._review('update',r,asdict(r),r.identity.uid[-1])
        if action=='diagnostics.read':
            async with self.scheduler.ble:
                try:
                    await self.ble.connect(a['target']);before=await self.ble.identity();history=await self.ble.history();after=await self.ble.identity()
                    if before!=after:raise ValueError('Identity changed during diagnostics')
                    result={'identity':asdict(before),'history':history};self.store.setting('last-diagnostic',result);return result
                finally:await self.ble.close()
        if action=='diagnostics.export':
            report=self.store.setting('last-diagnostic')
            if report is None:raise ValueError('Read a diagnostic report first')
            with Path(a['path']).open('x',encoding='utf-8') as f:json.dump(report,f,indent=2)
            return {'exported':True}
        if action=='probe.inspect':
            if self.probe:self.probe.close()
            self.probe=OpenOcdProbe(a['serial']);uid=self.probe.connect();profile=self.probe.watchdog()
            selected=self.candidate if a.get('candidate') else self.package
            policy=None
            if selected and selected.schema==3:
                from .core.packages import strict_json
                policy=strict_json(selected.entries()['first-install.json']).get('watchdogHandoff')
            return self._review('halt',(uid,policy,self.probe.generation),{'probe':a['serial'],'uid':[f'{x:08x}' for x in uid[:2]],'variant':uid[2],'watchdog':profile,'effect':'Halt CPU for original acquisition. No FLASH/UICR write. Physical model is not proven by MCU identity.'},f'{uid[1]:08x}')
        if action=='backup.capture':
            if not self.probe or not self.probe.halted:raise ValueError('Review and approve the named DK halt first')
            self.original=capture_original(self.probe,check=self.installer.check);self.store.put(self.original.raw,'original')
            self.export_path=str(self.store.export(self.original.digest,a['path']))
            return {'original':self.original.digest,'exported':self.export_path,'reopened':True,'targetHalted':True}
        if action=='backup.import':
            self.original=verify_original(Path(a['path']).read_bytes());self.store.put(self.original.raw,'original');self.export_path=str(Path(a['path']).absolute())
            if not self.store.reopen_receipt(self.original.digest,self.export_path):raise ValueError('Original reopen failed')
            return {'original':self.original.digest,'uid':self.original.identity[:2],'reopened':True}
        if action in ('first-install.preview','repair.preview','start.preview','bench.preview','bench.repair-preview','bench.start-preview'):
            if self.probe is None or self.original is None or self.export_path is None:raise ValueError('Inspect the DK, capture/import and reopen the protected original first')
            candidate_mode=action.startswith('bench.')
            selected=self.candidate if candidate_mode else self.need_package()
            if selected is None:raise ValueError('Choose the signed qualification candidate first')
            self.plan=prepare_install(self.original,selected)
            r=self.installer.review(self.plan,self.probe,self.export_path,resume_session=a.get('session') if action in ('repair.preview','bench.repair-preview') else None,start=action in ('start.preview','bench.start-preview'))
            return self._review(('bench-'+('start' if r.start else 'repair' if r.resume_session else 'first-install')) if candidate_mode else action.split('.')[0],r,{'qualification':'pending' if candidate_mode else 'qualified package',**self.plan.binding,'probe':self.probe.serial,'effect':'Explicit reset/start' if r.start else 'Bounded FLASH write; UICR preserved; ends halted'},f'{self.original.identity[1]:08x}')
        if action=='execute':
            token=a['review'];item=self.reviews.pop(token,None)
            if item is None:raise ValueError('Review expired or belongs to another process')
            kind,review=item
            if kind=='fleet':
                group,previews=review;group['state']='running';self.batches.save(group)
                for job,p in zip(group['jobs'],previews):
                    try:
                        async with self.batch_ble:
                            job['state']='running';self.batches.save(group)
                            job['session']=await self.engine.execute(self.need_package(),p,self.engine.approve(p));job['state']='await-operator'
                    except BaseException:
                        job['state']='interrupted';group['state']='paused';self.batches.save(group);raise
                    self.batches.save(group)
                group['state']='await-operator';self.batches.save(group);return group
            if kind=='zigbee':return {'session':await self.zigbee.execute(self.need_package(),review,self.zigbee.approve(review))}
            if kind in ('trial','prepare'):return {'session':await self.engine.execute(self.candidate if kind=='trial' else self.need_package(),review,self.engine.approve(review))}
            if kind=='update':return {'session':await self.engine.execute(self.need_package(),review,self.engine.approve(review))}
            if kind=='operator-confirm':self.store.record(review,'operator-confirmed');return {'operatorConfirmed':review}
            if kind=='halt':
                uid,policy,generation=review
                if self.probe.generation!=generation:raise ValueError('Halt review belongs to another live probe lease')
                self.probe.halt(uid,policy)
                return {'targetHalted':True,'flashWritten':False,'uicrWritten':False}
            if kind in ('first-install','repair','start','bench-first-install','bench-repair','bench-start'):return {'session':self.installer.execute(self.plan,self.probe,review,self.installer.approve(review)),'targetHalted':self.probe.halted}
            raise ValueError('Unknown reviewed operation')
        if action=='zigbee.preview':
            if self.mqtt is None:raise ValueError('Connect to the optional broker first')
            from .core.zigbee import ZigbeeEngine
            self.zigbee=self.zigbee or ZigbeeEngine(self.store,self.mqtt,self.scheduler,self.on_event)
            r=await self.zigbee.inspect(self.need_package(),a['network'],a['ieee'],a['source'])
            return self._review('zigbee',r,asdict(r),r.ieee[-8:])
        if action=='zigbee.reconcile':
            if not self.zigbee:raise ValueError('Connect to the matching broker first')
            return await self.zigbee.reconcile(a['session'])
        if action=='mqtt.save':
            networks=tuple(Network(**n) for n in a['networks']);p=Broker(a['uri'],networks,a.get('username',''),a.get('allow_plaintext',False)).validate()
            if a.get('password'):Credentials().set('mqtt',p.username,a['password'])
            self.store.setting('broker',asdict(p));return {'saved':True}
        if action=='mqtt.connect':
            value=self.store.setting('broker')
            if not value:raise ValueError('Configure an optional broker first')
            if self.mqtt:await self.mqtt.close()
            self.zigbee=None;value['networks']=tuple(Network(**n) for n in value['networks']);self.mqtt=MqttBridge(Broker(**value),Credentials());await self.mqtt.connect()
            from .core.zigbee import ZigbeeEngine
            self.scheduler.stopped=False;self.zigbee=ZigbeeEngine(self.store,self.mqtt,self.scheduler,self.on_event);return {'connected':True}
        if action=='mqtt.disconnect':
            if self.mqtt:await self.mqtt.close();self.mqtt=None
            return {'connected':False}
        if action=='mqtt.devices':return [{'network':n,'ieee':ieee,'record':d} for (n,ieee),d in (self.mqtt.devices.items() if self.mqtt else [])]
        if action=='settings.get':return {'source':self.store.setting('source') or 'Ryther/vomar','theme':self.store.setting('theme') or 'system','language':self.store.setting('language') or 'en','brokerConfigured':self.store.setting('broker') is not None}
        if action=='settings.save':
            for key in ('source','theme','language'):
                if key in a:self.store.setting(key,a[key])
            return await self.dispatch('settings.get')
        if action=='stop':self.stop();return {'stopped':True,'message':'A submitted remote operation may remain uncertain. Inspect before retrying.'}
        raise ValueError('Unknown application action')
    async def close(self):
        self.stop();await self.ble.close()
        if self.mqtt:await self.mqtt.close()
        if self.probe:self.probe.close()
        self.store.close()
