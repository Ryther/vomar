#!/usr/bin/env python3
"""Device-bound Z2M OTA upload/progress; no SWD and no global join changes."""
import argparse,asyncio,hashlib,json,re,struct,time,uuid
from pathlib import Path
UPDATE_TOPIC='bridge/response/device/ota_update/update'
def prepare_update(ieee,path,block_size=64):
 if type(block_size) is not int or block_size not in (32,48,64):raise ValueError("OTA block size must be 32, 48 or 64 bytes")
 if not re.fullmatch(r'0x[0-9a-f]{16}',ieee):raise ValueError('Exact lower-case IEEE required')
 data=Path(path).read_bytes()
 if len(data)<67 or len(data)>1024*1024:raise ValueError('Invalid OTA size')
 magic,version,hlen,flags,manufacturer,kind,release,stack=struct.unpack_from('<IHHHHHIH',data)
 total,hwmin,hwmax,tag,payload=struct.unpack_from('<IHHHI',data,52)
 if (magic,version,hlen,flags,manufacturer,kind,stack,hwmin,hwmax,tag)!=(0x0beef11e,0x100,60,4,0xfff1,0x3085,2,1,1,0) or total!=len(data) or payload!=len(data)-66:raise ValueError('Wrong OTA model/header/length')
 return {'id':ieee,'hex':{'file_name':f'vomar-{release:08x}-{hashlib.sha256(data).hexdigest()[:12]}.ota','data':data.hex()},'image_block_request_timeout':150000,'image_block_response_delay':10,'default_maximum_data_size':block_size}
def correlated_result(message,transaction):
 p=message.get('payload')
 return p if message.get('topic')==UPDATE_TOPIC and isinstance(p,dict) and p.get('transaction')==transaction else None
async def run(args):
 import websockets
 payload=prepare_update(args.ieee,args.image,args.block_size);transaction='vimar-ota-'+uuid.uuid4().hex;payload['transaction']=transaction
 cookie=args.cookie.read_text().strip();cookie=cookie[7:].strip() if cookie.lower().startswith('cookie:') else cookie
 url=args.url
 events=[];last_progress=-1;friendly=None;start=time.monotonic()
 args.output.parent.mkdir(parents=True,exist_ok=True)
 async with websockets.connect(url,origin=args.origin,additional_headers={'Cookie':cookie},max_size=8*1024*1024,close_timeout=1) as ws:
  async with asyncio.timeout(30):
   while friendly is None:
    m=json.loads(await ws.recv())
    if m.get('topic')=='bridge/devices':
     rows=m['payload'];rows=json.loads(rows) if isinstance(rows,str) else rows
     matches=[d for d in rows if d.get('ieee_address')==args.ieee]
     if len(matches)!=1:raise RuntimeError('Target missing or duplicated in selected coordinator')
     friendly=matches[0]['friendly_name']
  print(f'OTA Zigbee2MQTT: {friendly} ({args.ieee}), {len(payload["hex"]["data"])//2} bytes',flush=True)
  await ws.send(json.dumps({'topic':'bridge/request/device/ota_update/update','payload':payload}))
  async with asyncio.timeout(args.timeout):
   while True:
    m=json.loads(await ws.recv());result=correlated_result(m,transaction)
    if result is not None:
     events.append({'elapsed_s':round(time.monotonic()-start,2),'response':result});args.output.write_text(json.dumps(events,indent=2));print(json.dumps(result),flush=True)
     if result.get('status')!='ok':raise RuntimeError('Z2M OTA failed; evidence saved')
     return
    if m.get('topic')==friendly:
     p=m.get('payload');p=json.loads(p) if isinstance(p,str) else p
     if isinstance(p,dict) and isinstance(p.get('update'),dict):
      update=p['update'];progress=int(update.get('progress',0));record={'elapsed_s':round(time.monotonic()-start,2),'update':update};events.append(record)
      args.output.write_text(json.dumps(events,indent=2))
      if progress//5!=last_progress or update.get('state')!='updating':print(f'{record["elapsed_s"]:.0f}s {json.dumps(update)}',flush=True);last_progress=progress//5

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ieee',required=True);p.add_argument('--image',type=Path,required=True);p.add_argument('--url',required=True,help='Exact Zigbee2MQTT WebSocket API URL (ws:// or wss://)');p.add_argument('--origin',help='HTTP origin required by the proxy, if any');p.add_argument('--cookie',type=Path,default=Path('work/private/z2m-cookie.txt'));p.add_argument('--output',type=Path,required=True);p.add_argument('--timeout',type=int,default=2400);p.add_argument('--block-size',type=int,choices=(32,48,64),default=64);args=p.parse_args();asyncio.run(run(args))
if __name__=='__main__':main()
