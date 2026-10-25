"""One Paho broker connection; correlated Z2M requests and fresh observations."""
from __future__ import annotations
import asyncio
import base64
import json
import re
import secrets
import struct
import time
from urllib.parse import urlsplit
from tools.release.manifest import loads
from vomar_updater.core.fleet import Broker


def contract(value):
    if not isinstance(value,str) or not re.fullmatch('v1:[A-Za-z0-9_-]{58}',value):raise ValueError('Malformed OTA contract')
    raw=base64.urlsafe_b64decode(value[3:]+'==')
    if len(raw)!=43 or base64.urlsafe_b64encode(raw).decode().rstrip('=')!=value[3:] or raw[:2]!=b'\x01\x02' or raw[2] not in (0,1):raise ValueError('Malformed OTA contract')
    boot,sample=struct.unpack_from('<II',raw,3);ready=raw[2]==1
    if not ready and raw[11:]!=bytes(32):raise ValueError('Unready contract claims recovery hash')
    return {'boot':boot,'sample':sample,'ready':ready,'recovery':raw[11:].hex() if ready else ''}


class MqttBridge:
    def __init__(self,profile:Broker,credentials=None):
        self.profile=profile.validate();self.credentials=credentials;self.client=None;self.loop=None;self.connected=False
        self.devices={};self.observations={};self.pending={};self.birth=0;self.resource=None
    async def connect(self):
        from platformdirs import user_runtime_path
        from .locking import FileLease
        import hashlib
        name=hashlib.sha256(self.profile.uri.encode()).hexdigest()
        self.resource=FileLease(user_runtime_path('Vomar')/('mqtt-'+name+'.lock')).acquire()
        try:await self._connect()
        except BaseException:await self.close();raise
    async def _connect(self):
        import paho.mqtt.client as mqtt
        self.loop=asyncio.get_running_loop();uri=urlsplit(self.profile.uri)
        self.client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='vomar-'+secrets.token_hex(8),transport='websockets' if uri.scheme in ('ws','wss') else 'tcp',reconnect_on_failure=False)
        if self.profile.username:
            if self.credentials is None:raise ValueError('OS credential store required')
            password=self.credentials.get('mqtt',self.profile.username)
            if password is None:raise ValueError('Save the broker password in the OS credential store first')
            self.client.username_pw_set(self.profile.username,password)
        if uri.scheme in ('ssl','wss'):self.client.tls_set()
        if uri.scheme in ('ws','wss'):self.client.ws_set_options(path=uri.path or '/mqtt')
        ready=self.loop.create_future()
        def connected(client,userdata,flags,reason,properties):
            def apply():
                if reason.is_failure:
                    if not ready.done():ready.set_exception(ConnectionError('Broker connection was refused'))
                    return
                self.connected=True;self.birth+=1;self.devices.clear();self.observations.clear()
                client.subscribe([(n.topic+'/#',1) for n in self.profile.networks])
                if not ready.done():ready.set_result(None)
            self.loop.call_soon_threadsafe(apply)
        def disconnected(*_):self.loop.call_soon_threadsafe(self._offline)
        def message(_,userdata,msg):
            if len(msg.payload)>512*1024:return
            self.loop.call_soon_threadsafe(self.feed,msg.topic,bytes(msg.payload),bool(msg.retain))
        self.client.on_connect=connected;self.client.on_disconnect=disconnected;self.client.on_message=message
        await asyncio.to_thread(self.client.connect,uri.hostname,uri.port or (8883 if uri.scheme=='ssl' else 443 if uri.scheme=='wss' else 1883 if uri.scheme=='tcp' else 80),30)
        self.client.loop_start();await asyncio.wait_for(ready,15)
    def _offline(self):
        self.connected=False;self.devices.clear();self.observations.clear()
        for f in self.pending.values():
            if not f[2].done():f[2].set_exception(ConnectionError('Broker disconnected; submitted updates remain uncertain'))
    def feed(self,topic,raw,retained=False):
        try:value=loads(raw)
        except ValueError:return
        for network in self.profile.networks:
            if not topic.startswith(network.topic+'/'):continue
            relative=topic[len(network.topic)+1:]
            if relative=='bridge/state' and value in ({'state':'offline'},'offline'):self._offline();return
            if relative=='bridge/devices':
                for key in [k for k in self.devices if k[0]==network.id]:self.devices.pop(key)
                for key in [k for k in self.observations if k[0]==network.id]:self.observations.pop(key)
                if type(value) is not list or len(value)>512:return
                seen=set();names=set();records={}
                for d in value:
                    if type(d) is not dict:return
                    ieee=d.get('ieee_address');name=d.get('friendly_name');definition=d.get('definition')
                    if not isinstance(ieee,str) or not re.fullmatch('0x[0-9a-f]{16}',ieee) or ieee in seen:return
                    if not isinstance(name,str) or not 1<=len(name)<=256 or name in names or any(c in name for c in ('+','#')):return
                    if definition is not None and type(definition) is not dict:return
                    seen.add(ieee);names.add(name);records[(network.id,ieee)]=d
                self.devices.update(records)
            elif relative.startswith('bridge/response/device/ota_update/') and not retained and type(value) is dict:
                pending=self.pending.get(value.get('transaction'))
                if pending and pending[0]==topic and value.get('status')=='ok' and type(value.get('data')) is dict and value['data'].get('id')==pending[1] and not pending[2].done():pending[2].set_result(value['data'])
            elif not relative.startswith('bridge/') and type(value) is dict:
                candidates=[(k,d) for k,d in self.devices.items() if k[0]==network.id and relative in (d.get('friendly_name'),k[1])]
                if len(candidates)==1:self.observations[candidates[0][0]]={'value':value,'retained':retained,'at':time.monotonic(),'birth':self.birth}
    def network(self,network):
        n=next((n for n in self.profile.networks if n.id==network),None)
        if n is None:raise ValueError('Unknown MQTT network')
        return n
    def target(self,network,ieee):
        if not self.connected:raise ConnectionError('MQTT is offline')
        d=self.devices.get((network,ieee))
        definition=d.get('definition') if d else None
        if type(definition) is not dict or definition.get('vendor')!='OpenVimar' or definition.get('model')!='30805-custom' or d.get('model_id')!='Vimar30805' or d.get('disabled') is True or definition.get('supports_ota') is not True:raise ValueError('Selected device is not a discovered supported custom dimmer')
        return d
    async def publish(self,topic,payload):
        if not self.connected:raise ConnectionError('Broker disconnected')
        info=self.client.publish(topic,json.dumps(payload,separators=(',',':')),qos=1,retain=False)
        await asyncio.to_thread(info.wait_for_publish,10)
        if not info.is_published():raise ConnectionError('MQTT delivery uncertain')
    async def request(self,network,ieee,operation,source=None,timeout=30):
        self.target(network,ieee)
        if operation not in ('check','update'):raise ValueError('Unsupported OTA operation')
        tx='vomar-'+secrets.token_hex(16);n=self.network(network);future=asyncio.get_running_loop().create_future()
        self.pending[tx]=(n.topic+'/bridge/response/device/ota_update/'+operation,ieee,future)
        body={'id':ieee,'transaction':tx}
        if source:body['url']=source
        try:
            await self.publish(n.topic+'/bridge/request/device/ota_update/'+operation,body)
            return await asyncio.wait_for(future,timeout)
        finally:self.pending.pop(tx,None)
    async def verify_recovery(self,network,ieee,expected):
        self.target(network,ieee);baseline=None
        for _ in range(3):
            before=time.monotonic();await self.publish(self.network(network).topic+'/'+ieee+'/get',{'ota_contract':''})
            deadline=before+5
            while time.monotonic()<deadline:
                item=self.observations.get((network,ieee))
                if item and not item['retained'] and item['at']>before and item['birth']==self.birth:
                    next_value=contract(item['value'].get('ota_contract'))
                    if baseline and (next_value['boot']!=baseline['boot'] or 0<(next_value['sample']-baseline['sample'])&0xffffffff<0x80000000):
                        if not next_value['ready'] or next_value['recovery']!=expected:raise ValueError('Fresh recovery pair is incompatible; use Bluetooth migration')
                        return
                    baseline=next_value;break
                await asyncio.sleep(.05)
            await asyncio.sleep(.2)
        raise ValueError('No advancing non-retained recovery contract sample')
    async def close(self):
        if self.client:
            self.client.disconnect();await asyncio.to_thread(self.client.loop_stop);self.client=None
        self._offline()
        if self.resource:self.resource.close();self.resource=None
