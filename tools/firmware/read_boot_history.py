#!/usr/bin/env python3
"""Read/export authenticated recovery boot history. No upload, erase or reset.

Requires a recovery implementing project SMP groups0x8040/0x8041 and an existing
working authenticated BLE bond. Older deployed recovery may not support them.
Pins are SMP signed-region image hashes, not complete-file hashes. An existing
JSON export can also be checked offline without importing Bluetooth libraries.
"""
import argparse
import asyncio
from datetime import datetime,timezone
import io
import json
from pathlib import Path
import re
import struct
import cbor2
ROOT=Path(__file__).resolve().parents[2]
IDENTITY_GROUP=0x8040
HISTORY_GROUP=0x8041


def digest(value):
 if not isinstance(value,str) or not re.fullmatch('[0-9a-fA-F]{64}',value):raise ValueError('expected exact SHA256')
 return value.lower()


def uid(value):
 if not isinstance(value,str) or not re.fullmatch('[0-9a-fA-F]{8}:[0-9a-fA-F]{8}',value):raise ValueError('expected UID0:UID1, two8-digit hex words')
 return [int(word,16) for word in value.split(':')]


def uint(value,maximum):return type(value) is int and 0<=value<=maximum


def validate_history(history):
 keys={'protocol','record_size','capacity','current_image','sequence','pending_reason','state','entries'}
 if not isinstance(history,dict) or set(history)!=keys:raise ValueError('unsupported boot history fields')
 if any(type(history[k]) is not int or history[k]!=v for k,v in {'protocol':1,'record_size':88,'capacity':6,'current_image':1}.items()):raise ValueError('unsupported history format')
 if not uint(history['sequence'],0xffffffff) or not uint(history['pending_reason'],7):raise ValueError('invalid sequence/pending reason')
 state=history['state'];booleans={'initialized','loaded_valid','storage_valid'};results={'load_rc','decode_rc','save_rc','view_rc'}
 if not isinstance(state,dict) or set(state)!=booleans|results or any(type(state[k]) is not bool for k in booleans) or any(type(state[k]) is not int or not -0x80000000<=state[k]<=0x7fffffff for k in results):raise ValueError('invalid history state')
 if not isinstance(history['entries'],list) or len(history['entries'])>6:raise ValueError('unbounded history entries')
 for entry in history['entries']:
  if not isinstance(entry,dict) or set(entry)!={'seq','image','reason','raw_reset_flags'}:raise ValueError('invalid history entry')
  if not uint(entry['seq'],0xffffffff) or not uint(entry['raw_reset_flags'],0xffffffff) or not uint(entry['image'],1) or not uint(entry['reason'],7):raise ValueError('invalid history observation')
 return history


async def read_group(transport,group,sequence):
 # v2 READ command0, empty map; op/version/header are explicit and bounded.
 if group not in (IDENTITY_GROUP,HISTORY_GROUP):raise ValueError('read-only diagnostic group required')
 payload=b'\xa0';frame=struct.pack('>BBHHBB',8,0,len(payload),group,sequence,0)+payload
 response=bytes(await asyncio.wait_for(transport.send_and_receive(frame),timeout=20))
 if len(response)<8:raise ValueError('truncated SMP reply')
 op,flags,size,actual_group,actual_sequence,command=struct.unpack('>BBHHBB',response[:8])
 if (op,flags,actual_group,actual_sequence,command)!=(9,0,group,sequence,0) or size>2048 or len(response)!=size+8:raise ValueError('mismatched/unbounded SMP reply')
 stream=io.BytesIO(response[8:]);value=cbor2.CBORDecoder(stream).decode()
 if stream.read() or not isinstance(value,dict):raise ValueError('invalid/trailing CBOR reply')
 if value.get('rc') or 'err' in value:raise RuntimeError('Recovery does not support or refused the requested diagnostic READ: '+repr(value))
 return value


def verify_images(images,main_hash,recovery_hash):
 if not isinstance(images,list):raise ValueError('invalid image state')
 relevant=[i for i in images if isinstance(i,dict) and type(i.get('slot')) is int and i['slot'] in (0,1)]
 if len(relevant)!=2 or {i.get('slot') for i in relevant}!={0,1}:raise ValueError('ambiguous image slots')
 for image in relevant:
  expected=main_hash if image['slot']==0 else recovery_hash
  if digest(image.get('hash'))!=expected:raise ValueError('remote image hash differs from pinned target')
  if image['slot']==1 and image.get('active') is not True:raise ValueError('expected recovery is not active')


def verify_identity(identity,expected_uid):
 if not isinstance(identity,dict):raise ValueError('invalid live identity')
 actual_uid=identity.get('uid')
 if (type(identity.get('protocol')) is not int or identity['protocol']!=1 or
     identity.get('model')!='VIMAR30805' or type(identity.get('layout')) is not int or identity['layout']!=2 or
     not isinstance(actual_uid,list) or len(actual_uid)!=2 or not all(uint(word,0xffffffff) for word in actual_uid) or
     actual_uid!=expected_uid):raise ValueError('live identity does not match expected target')
 if not isinstance(identity.get('loader_sha256'),bytes) or len(identity['loader_sha256'])!=32:raise ValueError('missing bounded loader measurement')


async def collect(transport,read_images,expected_uid,main_hash,recovery_hash):
 main_hash,recovery_hash=digest(main_hash),digest(recovery_hash)
 before=await read_images();verify_images(before,main_hash,recovery_hash)
 identity=await read_group(transport,IDENTITY_GROUP,201);verify_identity(identity,expected_uid)
 history=validate_history(await read_group(transport,HISTORY_GROUP,202))
 after_identity=await read_group(transport,IDENTITY_GROUP,203);verify_identity(after_identity,expected_uid)
 if after_identity!=identity:raise ValueError('identity changed during diagnostic read')
 after=await read_images();verify_images(after,main_hash,recovery_hash)
 return dict(schema_version=1,observed_at_utc=datetime.now(timezone.utc).isoformat(),
  uid=expected_uid,loader_sha256=identity['loader_sha256'].hex(),images=after,history=history,
  interpretation='Raw observations only: zero reset flags or a pending intent do not prove a reset cause. '
   'CHORD labels a firmware-detected condition/request, not proven human input; '
   'ZIGBEE labels a recorded request, not its publisher or automation identity.')


def validate_export(report,expected_uid,main_hash,recovery_hash):
 if not isinstance(report,dict) or type(report.get('schema_version')) is not int or report['schema_version']!=1:raise ValueError('unsupported diagnostic export')
 verify_identity(dict(protocol=1,model='VIMAR30805',layout=2,uid=report.get('uid'),
  loader_sha256=bytes.fromhex(digest(report.get('loader_sha256')))),expected_uid)
 verify_images(report.get('images'),digest(main_hash),digest(recovery_hash))
 validate_history(report.get('history'))
 return report


async def run(args):
 from smpclient import SMPClient
 from smpclient.transport.ble import SMPBLETransport
 from smpclient.requests.image_management import ImageStatesRead
 from smpclient.generics import error
 destination=args.output.resolve()
 if destination.is_relative_to(ROOT/'inputs') or destination.exists():raise ValueError('export requires a new path outside immutable inputs')
 transport=SMPBLETransport()
 async with SMPClient(transport,args.address,timeout_s=20) as client:
  async def images():
   response=await client.request(ImageStatesRead())
   if error(response):raise RuntimeError(str(response))
   return [dict(slot=i.slot,active=i.active,version=i.version,hash=i.hash.hex()) for i in response.images]
  report=await collect(transport,images,uid(args.expected_uid),args.expected_main,args.expected_recovery)
 report['address']=args.address
 destination.parent.mkdir(parents=True,exist_ok=True)
 with destination.open('x') as output:json.dump(report,output,indent=2);output.write('\n')
 print(destination)


def main():
 parser=argparse.ArgumentParser(description=__doc__)
 mode=parser.add_mutually_exclusive_group(required=True)
 mode.add_argument('--address');mode.add_argument('--validate-export',type=Path)
 for name in ['expected-uid','expected-main','expected-recovery']:parser.add_argument('--'+name,required=True)
 parser.add_argument('--output',type=Path);args=parser.parse_args()
 uid(args.expected_uid);digest(args.expected_main);digest(args.expected_recovery)
 if args.validate_export:
  validate_export(json.loads(args.validate_export.read_text()),uid(args.expected_uid),args.expected_main,args.expected_recovery)
  print('Diagnostic export matches supplied UID/image hashes: '+str(args.validate_export))
 else:
  if args.output is None:parser.error('--output is required for a BLE read/export')
  asyncio.run(run(args))
if __name__=='__main__':main()
