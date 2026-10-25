#!/usr/bin/env python3
"""Compile an explicitly approved ordered public typed-record list to C.

This generates no approval, keys or per-device data. Input must already contain
finite exact known record types; it never infers family from a full-file hash.
"""
import argparse,json
from pathlib import Path
from loader_runtime_contract import validate_records,COMMON_KIND,ROOT

def generate(records):
 approved=validate_records(records)
 lines=['/* Generated finite public loader authority; no per-device data. */',
 '#ifndef VIMAR_GENERATED_LOADER_CONTRACTS_H','#define VIMAR_GENERATED_LOADER_CONTRACTS_H',
 '#include "loader_contract.h"','static const struct loader_contract_record vimar_loader_contracts[] = {']
 for record in approved:
  kind='LOADER_CONTRACT_COMMON_CODE44K_ANCHOR_V1' if record.kind==COMMON_KIND else 'LOADER_CONTRACT_LEGACY_FULL48K_SHA256'
  digest=','.join('0x'+record.sha256[i:i+2] for i in range(0,64,2))
  lines.append(' {.kind='+kind+',.digest={'+digest+'}},')
 lines+=['};',f'#define VIMAR_LOADER_CONTRACT_COUNT {len(approved)}U','#endif','']
 return '\n'.join(lines).encode('ascii')

def unique_fields(entries):
 result={}
 for key,value in entries:
  if key in result:raise ValueError("duplicate JSON authority field")
  result[key]=value
 return result

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--records',required=True,type=Path);parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
 if args.output.resolve().is_relative_to(ROOT/'inputs'):parser.error('immutable input output forbidden')
 if not args.records.is_file() or args.records.stat().st_size>16384:parser.error('bounded regular public record list required')
 try:result=generate(json.loads(args.records.read_text(),object_pairs_hook=unique_fields))
 except (ValueError,TypeError) as exc:parser.error(str(exc))
 with args.output.open('xb') as file:file.write(result)
if __name__=='__main__':main()
