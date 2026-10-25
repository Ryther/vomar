import asyncio,importlib.util,json,hashlib,argparse,struct
from intelhex import IntelHex
from pathlib import Path
from datetime import datetime,timezone
from bleak import BleakClient
from smpclient import SMPClient
from smpclient.transport.ble import SMPBLETransport
from smpclient.requests.image_management import ImageStatesRead
from smpclient.requests.os_management import ResetWrite
from smpclient.generics import error
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('console',OUT/'research_console.py');console=importlib.util.module_from_spec(spec);spec.loader.exec_module(console)
parser=argparse.ArgumentParser();parser.add_argument('--address',required=True);args=parser.parse_args();ADDR=args.address
def log(event,**data):
 row=dict(time=datetime.now(timezone.utc).isoformat(),event=event,**data)
 with (OUT/'logs/bootstrap-ota-events.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
 print(json.dumps(row),flush=True)
async def main():
 data=(OUT/'restore-bootstrap.signed.bin').read_bytes()
 manifest=json.loads((OUT/'artifact-manifest.json').read_text())
 assert hashlib.sha256(data).hexdigest()==manifest['artifacts']['restore-bootstrap.signed.bin']['sha256']
 recovery=IntelHex(str(OUT/'recovery.signed.hex'))
 hdr=bytes(recovery[a] for a in range(0xb0000,0xb0020))
 header_size,protected_size,img_size=struct.unpack_from('<HHI',hdr,8)
 assert 32<=header_size<=4096 and 0<img_size<0x40000
 expected_hash=hashlib.sha256(bytes(recovery[a] for a in range(0xb0000,0xb0000+header_size+img_size+protected_size))).hexdigest()
 log('bootstrap_artifact',size=len(data),sha256=hashlib.sha256(data).hexdigest())
 if ADDR.upper()!=manifest['normal_ble_address'].upper():
  raise RuntimeError('Address does not match this device package')
 log('requires_independent_ble_recovery',address=ADDR)
 transport=SMPBLETransport()
 async with SMPClient(transport,ADDR,timeout_s=45) as c:
  state=await c.request(ImageStatesRead());assert not error(state),state
  assert any(i.active and i.slot==1 and i.hash.hex()==expected_hash for i in state.images),state
  last=0
  async for offset in c.upload(data,first_timeout_s=60):
   if offset-last>=50000 or offset==len(data):log('bootstrap_upload_progress',offset=offset,size=len(data));last=offset
  log('bootstrap_uploaded')
  response=await c.request(ResetWrite());assert not error(response),response
  log('bootstrap_boot_requested')
asyncio.run(main())
