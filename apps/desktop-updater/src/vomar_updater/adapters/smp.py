"""Bounded SMP wire codec and Bleak transport for project firmware."""
from __future__ import annotations
import asyncio
import hashlib
import struct
import sys
import cbor2
from vomar_updater.core.engine import Identity,COMMON,LEGACY

SERVICE='8d53dc1d-1db7-4cd3-868b-8a527460aa84'
CHARACTERISTIC='da2e7828-fbce-4e01-ae9e-261174997c48'

class UnsupportedCommand(ValueError):pass


def decode_cbor(raw,*,signed=False):
    if not 1<=len(raw)<=4096:raise ValueError('CBOR response bound')
    offset=0
    def byte():
        nonlocal offset
        if offset>=len(raw):raise ValueError('Truncated CBOR')
        x=raw[offset];offset+=1;return x
    def number(extra):
        if extra<24:return extra
        if extra not in (24,25,26):raise ValueError('Unsupported CBOR integer width')
        n=0
        for _ in range({24:1,25:2,26:4}[extra]):n=n*256+byte()
        return n
    def item(depth=0):
        nonlocal offset
        if depth>3:raise ValueError('CBOR nesting bound')
        head=byte();major=head>>5;extra=head&31
        if major==0:return number(extra)
        if major==1 and signed:return -1-number(extra)
        if major in (2,3):
            length=number(extra)
            if length>256 or length>len(raw)-offset:raise ValueError('CBOR string bound')
            value=raw[offset:offset+length];offset+=length
            return value if major==2 else value.decode('utf-8',errors='strict')
        if major in (4,5):
            indefinite=extra==31;count=0 if indefinite else number(extra)
            if count>8:raise ValueError('CBOR container bound')
            out=[] if major==4 else {};n=0
            while (offset<len(raw) and raw[offset]!=255) if indefinite else n<count:
                if n>=8:raise ValueError('CBOR container bound')
                value=item(depth+1)
                if major==4:out.append(value)
                else:
                    if not isinstance(value,str) or value in out:raise ValueError('Duplicate/non-text CBOR key')
                    out[value]=item(depth+1)
                n+=1
            if indefinite and byte()!=255:raise ValueError('Missing CBOR terminator')
            return out
        if major==7 and extra in (20,21):return extra==21
        raise ValueError('Unsupported CBOR scalar')
    result=item()
    if offset!=len(raw) or type(result) is not dict:raise ValueError('Exactly one CBOR map required')
    return result


def packet(op,group,command,sequence,payload):
    data=cbor2.dumps(payload)
    return struct.pack('>BBHHBB',op,0,len(data),group,sequence,command)+data


def parse_packet(raw,op,group,command,sequence):
    if len(raw)<8:raise ValueError('Truncated SMP header')
    actual,flags,length,g,seq,cmd=struct.unpack('>BBHHBB',raw[:8])
    if actual&7!=op+1 or actual>>3 not in (0,1) or flags or length!=len(raw)-8 or (g,cmd,seq)!=(group,command,sequence):raise ValueError('SMP response header mismatch')
    return decode_cbor(raw[8:],signed=group==0x8041)


def decode_identity(m,command):
    expected={'protocol','model','layout','uid','loader' if command==1 else 'loader_sha256'}
    if set(m)!=expected or type(m['protocol']) is not int or m['protocol']!=command+1 or m['model']!='VIMAR30805' or type(m['layout']) is not int or m['layout']!=2:raise ValueError('Unsupported runtime identity')
    uid=m['uid']
    if type(uid) is not list or len(uid)!=2 or any(type(x) is not int or not 0<=x<=0xffffffff for x in uid):raise ValueError('Malformed runtime UID')
    kind=LEGACY;anchor=None
    if command==1:
        loader=m['loader']
        if type(loader) is not dict:raise ValueError('Typed loader required')
        kind=loader.get('kind');digest=loader.get('digest')
        if kind not in (COMMON,LEGACY) or set(loader)!=({'kind','digest','anchor_sha256'} if kind==COMMON else {'kind','digest'}):raise ValueError('Unknown loader contract')
        if kind==COMMON:
            anchor=loader['anchor_sha256']
            if not isinstance(anchor,bytes) or len(anchor)!=32:raise ValueError('Anchor digest required')
            anchor=anchor.hex()
    else:digest=m['loader_sha256']
    if not isinstance(digest,bytes) or len(digest)!=32:raise ValueError('Loader digest required')
    result=Identity(command+1,m['model'],2,tuple(f'{x:08x}' for x in uid),kind,digest.hex(),anchor);result.validate();return result


class BleakSmp:
    """One owned connection; no unpair, automatic retry or reconnect after writes.

    `authenticated` records successful OS pairing plus a response on the firmware
    characteristic configured AUTHEN. It is BLE-reported identity, not attestation.
    macOS pairs when that protected characteristic is accessed, per CoreBluetooth.
    """
    def __init__(self):
        self.client=None;self.authenticated=False;self.sequence=0;self._serial=asyncio.Lock();self._response=None;self._buffer=bytearray();self.security_evidence='not connected'
    @staticmethod
    async def scan(timeout=8):
        from bleak import BleakScanner
        found=await BleakScanner.discover(timeout=timeout,return_adv=True,service_uuids=[SERVICE])
        return [{'id':d.address,'name':a.local_name or d.name or 'Unnamed recovery','rssi':a.rssi} for d,a in found.values()]
    async def connect(self,target):
        if self.client is not None:await self.close()
        if sys.platform not in ('linux','darwin','win32'):raise ValueError('Unsupported Bluetooth security backend')
        from bleak import BleakClient,BleakScanner
        device=await BleakScanner.find_device_by_address(target,timeout=10)
        if device is None:raise ValueError('Recovery not found. Enable Bluetooth and put the dimmer in recovery.')
        self.client=BleakClient(device,pair=sys.platform!='darwin',timeout=60,disconnected_callback=self._disconnected)
        try:
            await self.client.connect()
            if sys.platform=='win32':await self.client.pair(protection_level=3)
            await self.client.start_notify(CHARACTERISTIC,self._notify)
            self.security_evidence='OS pairing completed; awaiting authenticated project characteristic' if sys.platform!='darwin' else 'CoreBluetooth handles pairing on protected characteristic access'
        except BaseException:
            await self.close();raise
    def _disconnected(self,_):
        self.authenticated=False
        if self._response and not self._response.done():self._response.set_exception(ConnectionError('Bluetooth disconnected; inspect before retry'))
    def _notify(self,_,data):
        if not self._response or self._response.done():return
        self._buffer.extend(data)
        if len(self._buffer)>4104:self._response.set_exception(ValueError('SMP response bound'));return
        if len(self._buffer)>=8:
            length=struct.unpack_from('>H',self._buffer,2)[0]+8
            if len(self._buffer)==length:self._response.set_result(bytes(self._buffer))
            elif len(self._buffer)>length:self._response.set_exception(ValueError('SMP trailing frame'))
    async def request(self,op,group,command,payload):
        async with self._serial:
            if not self.client or not self.client.is_connected:raise ConnectionError('Bluetooth connection closed')
            self.sequence=(self.sequence+1)%256;seq=self.sequence
            self._buffer=bytearray();self._response=asyncio.get_running_loop().create_future()
            raw=packet(op,group,command,seq,payload)
            try:
                for offset in range(0,len(raw),min(244,max(20,self.client.mtu_size-3))):
                    await self.client.write_gatt_char(CHARACTERISTIC,raw[offset:offset+min(244,max(20,self.client.mtu_size-3))],response=False)
                result=parse_packet(await asyncio.wait_for(self._response,20),op,group,command,seq)
                if result=={'rc':8}:raise UnsupportedCommand('Project command unavailable on this recovery')
                if ('rc' in result and (type(result['rc']) is not int or result['rc']!=0)) or 'err' in result:raise ValueError('Recovery refused the operation')
                return result
            finally:self._response=None;self._buffer=bytearray()
    async def identity(self):
        try:i=decode_identity(await self.request(0,0x8040,1,{}),1)
        except UnsupportedCommand:i=decode_identity(await self.request(0,0x8040,0,{}),0)
        self.authenticated=True;self.security_evidence='OS-managed pairing and authenticated project characteristic response; no hardware attestation';return i
    async def images(self):
        m=await self.request(0,1,0,{})
        images=m.get('images')
        if type(images) is not list or not 1<=len(images)<=4:raise ValueError('Bounded image state required')
        result={}
        for i in images:
            if type(i) is not dict or type(i.get('slot')) is not int or i['slot'] not in (0,1) or i.get('image',0)!=0:raise ValueError('Unsupported image slot')
            name='primary' if i['slot']==0 else 'recovery'
            if name in result:raise ValueError('Duplicate image slot')
            h=i.get('hash')
            if h is not None and (not isinstance(h,bytes) or len(h)!=32):raise ValueError('Malformed image hash')
            if type(i.get('active')) is not bool or type(i.get('bootable')) is not bool:raise ValueError('Image flags must be booleans')
            result[name]={'hash':h.hex() if h else None,'active':i['active'],'bootable':i['bootable'],'version':i.get('version')}
        return result
    async def upload(self,raw,progress):
        offset=0
        while offset<len(raw):
            data={'off':offset,'data':raw[offset:offset+128]}
            if offset==0:data.update(len=len(raw),sha=hashlib.sha256(raw).digest())
            r=await self.request(2,1,1,data);next_offset=r.get('off')
            if type(next_offset) is not int or next_offset!=min(offset+128,len(raw)):raise ValueError('Unexpected upload offset; preserve interrupted session')
            offset=next_offset;await progress(offset)
    async def reset(self):
        r=await self.request(2,0,5,{})
        if r not in ({},{'rc':0}):raise ValueError('Malformed reset acknowledgment')
        return True
    async def migration(self,primary,recovery):
        r=await self.request(2,0x8042,0,{'hash':bytes.fromhex(primary)})
        if r!={'accepted':True}:raise ValueError('Migration boot refused')
        return True
    async def history(self):return await self.request(0,0x8041,0,{})
    async def close(self):
        self.authenticated=False;client=self.client;self.client=None
        if client is not None:
            await client.disconnect()
