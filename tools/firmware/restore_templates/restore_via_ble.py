"""Device-bound Vimar restore client candidate. Executes restoration only when explicitly invoked."""
import argparse,asyncio,json,struct,time
from pathlib import Path
from datetime import datetime,timezone
from bleak import BleakClient,BleakScanner
from dbus_fast import BusType,DBusError
from dbus_fast.errors import InterfaceNotFoundError
from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface,method
ROOT=Path(__file__).resolve().parent
ADDRESS='@VIMAR_RESTORE_BLE_ADDRESS@'
PATH='/org/bluez/hci0/dev_'+ADDRESS.replace(':','_')
SERVICE='fde30805-c001-4a40-8d00-308050000010'
COMMAND='fde30805-c001-4a40-8d00-308050000011'
BOOT=0xc000;START=0xb0000;END=0xef000;PAGE=4096
UID=(0x@VIMAR_UID0@,0x@VIMAR_UID1@)

def log(event,**data):
 row=dict(time=datetime.now(timezone.utc).isoformat(),event=event,**data)
 with (ROOT/'logs/restore-events.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
 print(json.dumps(row),flush=True)

class Agent(ServiceInterface):
 def __init__(self):super().__init__('org.bluez.Agent1')
 @method()
 def Release(self):pass
 @method()
 def Cancel(self):pass
 @method()
 def RequestPasskey(self,device:'o')->'u':
  if device!=PATH:raise DBusError('org.bluez.Error.Rejected','Not the restore probe')
  return 824005
 @method()
 def RequestConfirmation(self,device:'o',passkey:'u'):
  if device!=PATH or passkey!=824005:raise DBusError('org.bluez.Error.Rejected','Unexpected confirmation')
 @method()
 def AuthorizeService(self,device:'o',uuid:'s'):
  if device!=PATH:raise DBusError('org.bluez.Error.Rejected','Not the restore probe')

async def pair_fresh():
 # The restorer keeps bonds in RAM until reset. Never discard a working host
 # bond between client invocations: it would desynchronize the two peers.
 bus_check=await MessageBus(bus_type=BusType.SYSTEM).connect()
 try:
  props=bus_check.get_proxy_object('org.bluez',PATH,await bus_check.introspect('org.bluez',PATH)).get_interface('org.freedesktop.DBus.Properties')
  paired=(await props.call_get('org.bluez.Device1','Paired')).value
 except (DBusError,InterfaceNotFoundError):paired=False
 finally:bus_check.disconnect()
 if paired:
  try:
   async with BleakClient(ADDRESS,timeout=12) as existing:
    raw=bytes(await existing.read_gatt_char(COMMAND))
    if len(raw)!=20:raise RuntimeError('Invalid authenticated reply')
   log('existing_restore_bond_reused')
   return
  except Exception as exc:log('stale_restore_bond',error=repr(exc))
 bus=await MessageBus(bus_type=BusType.SYSTEM).connect();agent_path='/com/vimar/DKRestoreProbeAgent'
 manager=bus.get_proxy_object('org.bluez','/org/bluez',await bus.introspect('org.bluez','/org/bluez')).get_interface('org.bluez.AgentManager1')
 adapter=bus.get_proxy_object('org.bluez','/org/bluez/hci0',await bus.introspect('org.bluez','/org/bluez/hci0')).get_interface('org.bluez.Adapter1')
 bus.export(agent_path,Agent())
 await manager.call_register_agent(agent_path,'KeyboardOnly')
 try:
  # Exact temporary restore MAC only. Main/recovery DK bond is left untouched.
  try:await adapter.call_remove_device(PATH)
  except DBusError as exc:
   if exc.type not in ('org.bluez.Error.DoesNotExist','org.bluez.Error.InvalidArguments'):raise
  await asyncio.sleep(1)
  device=await BleakScanner.find_device_by_address(ADDRESS,timeout=30)
  if device is None:raise RuntimeError('DK scratch restorer not advertising')
  proxy=bus.get_proxy_object('org.bluez',PATH,await bus.introspect('org.bluez',PATH)).get_interface('org.bluez.Device1')
  for attempt in range(3):
   try:
    await asyncio.wait_for(proxy.call_pair(),timeout=45)
    break
   except DBusError:
    if attempt==2:raise
    try:await proxy.call_disconnect()
    except DBusError:pass
    await asyncio.sleep(2)
  await proxy.call_disconnect()
  await asyncio.sleep(1)
  log('ephemeral_restore_link_paired',address=ADDRESS)
 finally:
  await manager.call_unregister_agent(agent_path);bus.unexport(agent_path);bus.disconnect()

class Probe:
 def __init__(self,client):self.client=client;self.sequence=0;self.chunk_size=20
 async def init(self):
  if self.client.services.get_service(SERVICE) is None:raise RuntimeError('Wrong service')
  await self.client._backend._acquire_mtu()
  self.chunk_size=min(232,self.client.mtu_size-3-12)
  if self.chunk_size<=0:raise RuntimeError('MTU too small')
  info=await self.command(0)
  if (info[4],info[5])!=UID or not info[6]&1:raise RuntimeError('Wrong target UID')
  log('restore_target_verified',mtu=self.client.mtu_size,chunk=self.chunk_size)
 async def command(self,op,address=0,arg=0,payload=b'',check=True,read=True):
  self.sequence=(self.sequence+1)&0xffff;seq=self.sequence
  packet=struct.pack('<BBHII',1,op,seq,address,arg)+payload
  await self.client.write_gatt_char(COMMAND,packet,response=op!=1 or read)
  if not read:return
  raw=bytes(await self.client.read_gatt_char(COMMAND))
  if len(raw)!=20:raise RuntimeError('Invalid reply size')
  result=struct.unpack('<BBHiIII',raw)
  if result[:3]!=(1,op,seq):raise RuntimeError('Reply sequence mismatch')
  if check and result[3]!=0:raise RuntimeError(f'Device rejected operation {op} page {address:x}: {result}')
  return result
 async def stage(self,address,data):
  for off in range(0,len(data),self.chunk_size):
   await self.command(1,address,off,data[off:off+self.chunk_size],read=False)
 async def page(self,address,data):
  state=await self.command(3,address,check=False)
  if state[3]==0:return False
  await self.stage(address,data)
  await self.command(2,address)
  return True

async def session():
 await pair_fresh()
 client=BleakClient(ADDRESS,timeout=30)
 await client.connect();probe=Probe(client)
 try:await probe.init()
 except BaseException:await client.disconnect();raise
 return client,probe

async def run(action):
 data=(ROOT/'stock-flash.bin').read_bytes()
 import hashlib
 if hashlib.sha256(data).hexdigest()!='@VIMAR_STOCK_FLASH_SHA256@':raise RuntimeError('Wrong stock backup')
 if len(data)!=0x100000 or data[START:END]!=b'\xff'*(END-START):raise RuntimeError('Reference layout invalid')
 client,probe=await session()
 try:
  if action=='reset':
   result=await probe.command(3,BOOT,check=False)
   log('committed_page_status_before_reset',status=result[3])
   try:await probe.command(7)
   except Exception as exc:log('ordinary_reset_link_closed',error=repr(exc))
   log('ordinary_reset_requested_without_bootmode')
  elif action=='restore':
   started=time.monotonic();count=0
   for address in range(BOOT,len(data),PAGE):
    if START<=address<END:continue
    count+=int(await probe.page(address,data[address:address+PAGE]))
    if count and count%16==0:log('stream_progress',address=hex(address),pages_written=count,seconds=round(time.monotonic()-started,1))
   for address in range(0,BOOT,PAGE):await probe.page(address,data[address:address+PAGE])
   log('all_pages_staged',seconds=round(time.monotonic()-started,1))
   await probe.command(4);log('final_prepare_verified')
   await probe.command(5,arg=0x52535452);log('finalize_acknowledged')
  else:
   result=await probe.command(3,BOOT,check=False)
   log('first_primary_page_status',status=result[3])
 finally:
  if client.is_connected:await client.disconnect()

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('action',choices=['info','restore','reset']);args=parser.parse_args()
 asyncio.run(run(args.action))
