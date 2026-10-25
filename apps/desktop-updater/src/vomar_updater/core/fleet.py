"""Private device organization and bounded independent transport lanes."""
from __future__ import annotations
import asyncio
from dataclasses import asdict,dataclass
import json
import re
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Network:
    id:str
    label:str
    topic:str


@dataclass(frozen=True)
class Broker:
    uri:str
    networks:tuple[Network,...]
    username:str=''
    allow_plaintext:bool=False
    def validate(self):
        try:u=urlsplit(self.uri);port=u.port
        except ValueError:raise ValueError('Invalid broker address') from None
        if u.scheme not in ('tcp','ssl','ws','wss') or not u.hostname or u.username or u.password or u.query or u.fragment or (u.scheme in ('tcp','ssl') and u.path) or port is not None and not 1<=port<=65535:raise ValueError('Use a broker host without embedded credentials, query or fragment')
        if u.scheme in ('tcp','ws') and not self.allow_plaintext:raise ValueError('Explicit unencrypted local-network consent required')
        if not 1<=len(self.networks)<=3 or len({n.id for n in self.networks})!=len(self.networks) or len({n.label.strip().casefold() for n in self.networks})!=len(self.networks):raise ValueError('Configure one to three distinct networks')
        for n in self.networks:
            if not re.fullmatch('[A-Za-z0-9_-]{1,64}',n.id) or not 1<=len(n.label.strip())<=128 or not 1<=len(n.topic)<=256 or any(not part.strip() for part in n.topic.split('/')) or any(c in '+#' or ord(c)<32 for c in n.topic):raise ValueError('Use exact non-overlapping MQTT topics without wildcards')
        for i,n in enumerate(self.networks):
            if any(n.topic==o.topic or n.topic.startswith(o.topic+'/') or o.topic.startswith(n.topic+'/') for o in self.networks[i+1:]):raise ValueError('MQTT base topics overlap')
        return self


class Registry:
    def __init__(self,store):self.store=store
    @staticmethod
    def validate(record):
        allowed={'id','name','room','ble','ieee','network'}
        if type(record) is not dict or set(record)!=allowed or any(not isinstance(x,str) for x in record.values()) or not re.fullmatch('[A-Za-z0-9_.:-]{1,128}',record['id']):raise ValueError('Invalid registry record')
        if not 1<=len(record['name'].strip())<=128 or len(record['room'])>128 or len(record['ble'])>128:raise ValueError('Device name/room/address exceeds bounds')
        if record['ieee'] and not re.fullmatch('0x[0-9a-f]{16}',record['ieee']):raise ValueError('Exact IEEE address required')
        if record['network'] and not re.fullmatch('[A-Za-z0-9_-]{1,64}',record['network']):raise ValueError('Invalid network reference')
        return record
    def save(self,record):
        self.validate(record)
        with self.store.db:self.store.db.execute('INSERT OR REPLACE INTO devices VALUES(?,?)',(record['id'],json.dumps(record)))
    def list(self):return [json.loads(r[0]) for r in self.store.db.execute('SELECT record FROM devices ORDER BY id')]
    def import_records(self,raw):
        from tools.release.manifest import loads
        if len(raw)>512*1024:raise ValueError('Registry import bound')
        rows=loads(raw)
        if type(rows) is not list or len(rows)>512 or len({r.get('id') for r in rows if isinstance(r,dict)})!=len(rows):raise ValueError('Bounded unique registry required')
        for r in rows:self.validate(r)
        with self.store.db:
            for r in rows:self.store.db.execute('INSERT OR REPLACE INTO devices VALUES(?,?)',(r['id'],json.dumps(r)))
        return len(rows)
    def remove(self,device_id):
        with self.store.db:self.store.db.execute('DELETE FROM devices WHERE id=?',(device_id,))


class Scheduler:
    def __init__(self):self.ble=asyncio.Lock();self.sequential=asyncio.Lock();self.networks={};self.pending=0;self.stopped=False
    async def run(self,lane,work,*,parallel=True):
        if self.pending>=256:raise ValueError('Fleet queue is full')
        if lane!='ble' and not re.fullmatch('network:[A-Za-z0-9_-]{1,64}',lane):raise ValueError('Unknown transport lane')
        lock=self.ble if lane=='ble' else self.networks.setdefault(lane,asyncio.Lock());self.pending+=1
        try:
            async with lock:
                if self.stopped:raise asyncio.CancelledError('Fleet stopped; server-side MQTT operations may remain active')
                if parallel:return await work()
                async with self.sequential:return await work()
        finally:self.pending-=1
    def stop(self):self.stopped=True


class Batches:
    """Organization is durable; executable reviews/approvals remain process-local."""
    def __init__(self,store):self.store=store
    def create(self,package,targets,mode='sequential'):
        import secrets,time
        if mode not in ('sequential','network-parallel') or not 1<=len(targets)<=256:raise ValueError('Invalid bounded batch')
        group={'id':secrets.token_hex(16),'package':package,'mode':mode,'created':time.time(),'state':'paused','jobs':[{'target':t,'state':'queued','session':None} for t in targets]}
        self.save(group);return group
    def save(self,group):self.store.setting('batch:'+group['id'],group)
    def list(self):
        rows=self.store.db.execute("SELECT value FROM settings WHERE name LIKE 'batch:%'").fetchall()
        return [json.loads(r[0]) for r in rows]
