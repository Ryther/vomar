#!/usr/bin/env python3
"""Decode exported read-only fault chunks. No radio, upload, reset or flash access."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import zlib

FIELDS = [
 ('uptime_ms',40,0,False),('source',44,1,False),('line',48,2,True),
 ('error',52,3,True),('lr',56,4,False),('msp',60,5,False),('psp',64,6,False),
 ('ipsr',68,7,False),('control',72,8,False),('gpregret',76,9,False),
 ('signal',80,10,False),('signal_status',84,11,True),('stage',88,12,False),
 ('role',92,13,False),('report_kind',96,14,False),('report_length',100,15,False),
 ('report_status',104,16,True),('phase',108,17,False),
]

def decode_record(data,expected_build=None):
 if not isinstance(data,bytes) or len(data)!=128:raise ValueError('Expected128-byte record')
 magic,version,length,sequence,boot=struct.unpack_from('<IHHII',data)
 valid,kind=struct.unpack_from('<II',data,32)
 crc,commit=struct.unpack_from('<II',data,120)
 if (magic,length,commit)!=(0x46444941,128,0x434f4d54) or version not in (1,2) or kind not in (1,2,3) or valid>>(18 if version==1 else 21) or data[112:120]!=bytes(8) or sequence==0 or zlib.crc32(data[:120])!=crc:
  raise ValueError('Uncommitted, unknown-format or corrupt diagnostic record')
 required={1:6,2:14,3:1008}[kind]
 if valid&required!=required:raise ValueError('Missing required diagnostic fields')
 if kind in (1,2) and (valid&1008 or (kind==2)!=(bool(valid&8))):raise ValueError('Invalid cause field mask')
 if kind==3 and valid&14:raise ValueError('Abort cannot invent an original checked cause')
 build=data[16:32]
 queue_flags=valid&0x1c0000
 if queue_flags and (version!=2 or kind!=2 or not valid&0x40000):raise ValueError('Invalid queue field mask')
 result={'format':version,'sequence':sequence,'boot_sequence':boot,'build_id':build.hex(),
         'kind':{1:'assert',2:'checked_error',3:'abort'}[kind],'valid':valid}
 if expected_build is not None:
  if not isinstance(expected_build,bytes) or len(expected_build)!=16:raise ValueError('Expected16-byte build ID')
  result['matches_expected_build']=build==expected_build
 for name,offset,bit,signed in FIELDS:
  if valid&(1<<bit):result[name]=struct.unpack_from('<i' if signed else '<I',data,offset)[0]
 if version==2 and kind==2:
  result['attempted_callback']=None
  if valid&0x40000:
   capacity,used,read,write,head,tail=struct.unpack_from('<6I',data,56)
   consistent=capacity==32 and used<=32 and read<32 and write<32 and (read+used)%32==write
   result['queue']={'capacity':capacity,'used':used,'read_index':read,'write_index':write,
     'head_callback':head if valid&0x80000 else None,'tail_callback':tail if valid&0x100000 else None,
     'consistent':consistent}
 if kind==2:
  source=result['source'];tag=source>>24;severity=(source>>16)&0xff
  if tag==0xa0 and severity!=1 and source&0xffff==0 and result['line']==-2147483648:
   result.update(kind='sdk_error',severity=severity,original_location_present=False)
  elif tag==0xa1 and severity==0xff:
   result.update(kind='sdk_error',severity=severity,original_location_present=True,
                 original_file_id=source&0xffff,original_line=result['line'])
 return result

def decode_chunks(state,expected_build=None):
 if not isinstance(state,dict):raise ValueError('Expected MQTT state object')
 chunks=[]
 for i in range(8):
  value=state.get(f'fault_diagnostic_{i}')
  if not isinstance(value,str) or not re.fullmatch('[0-9a-fA-F]{64}',value):raise ValueError('Missing or malformed diagnostic chunk'+str(i))
  chunks.append(bytes.fromhex(value))
 raw=b''.join(chunks);records=[]
 for slot in range(2):
  data=raw[slot*128:(slot+1)*128]
  if data!=bytes(128):
   decoded=decode_record(data,expected_build)
   if (slot==1)!=(decoded['kind']=='abort'):raise ValueError('Record kind in wrong slot')
   records.append({'slot':slot,**decoded})
 if len(records)==2:
  first,last=records;next_sequence=(first['sequence']+1)&0xffffffff
  if next_sequence==0:next_sequence=1
  if first['build_id']!=last['build_id'] or first['boot_sequence']!=last['boot_sequence'] or last['sequence']!=next_sequence:
   raise ValueError('Mixed diagnostic captures; repeat all chunk reads')
 return {'status':state.get('fault_diagnostic_status'),'records':records,
  'interpretation':'Raw captured evidence. Match build ID to its archived ELF before resolving addresses. Cached uptime is a breadcrumb; SRAM may be lost on power failure.'}

def resolve_callbacks(decoded,elf_path):
 """Resolve only against an ELF carrying the captured immutable build identity."""
 from elftools.elf.elffile import ELFFile
 from elftools.elf.sections import SymbolTableSection
 with Path(elf_path).open('rb') as stream:
  elf=ELFFile(stream)
  symbols=[sym for section in elf.iter_sections() if isinstance(section,SymbolTableSection) for sym in section.iter_symbols()]
  identities=[]
  for sym in symbols:
   if sym.name=='vimar_fault_build_id' and sym['st_size']==16 and isinstance(sym['st_shndx'],int):
    section=elf.get_section(sym['st_shndx']);offset=sym['st_value']-section['sh_addr']
    identities.append(section.data()[offset:offset+16].hex())
  if not identities or any(identity!=decoded['build_id'] for identity in identities):
   raise ValueError('ELF build identity does not match captured record')
  result={'elf_sha256':hashlib.sha256(Path(elf_path).read_bytes()).hexdigest(),'callbacks':{}}
  for name in ('head_callback','tail_callback'):
   address=decoded.get('queue',{}).get(name)
   resolved=None
   if address is not None:
    code=address&~1
    for sym in symbols:
     start=sym['st_value']&~1
     if sym['st_info']['type']=='STT_FUNC' and sym['st_size'] and start<=code<start+sym['st_size']:
      resolved={'symbol':sym.name,'offset':code-start};break
   result['callbacks'][name]=resolved
  return result

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('export',type=Path);parser.add_argument('--build-id');parser.add_argument('--elf',type=Path);args=parser.parse_args()
 expected=bytes.fromhex(args.build_id) if args.build_id else None
 result=decode_chunks(json.loads(args.export.read_text()),expected)
 if args.elf:
  for record in result['records']:record['symbol_resolution']=resolve_callbacks(record,args.elf)
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()
