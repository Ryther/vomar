#!/usr/bin/env python3
"""Measure public loader artifacts into explicit versioned contract records.

No device, keys, backup, anchor write or approval operation. A common record
measures only the explicitly fixed domain+44KiB code span; runtime admission
still needs an approved record and live committed-anchor/FICR/UICR validation.
Input is an exact canonical48KiB loader artifact; no truncation/mask option.
"""
from dataclasses import dataclass
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]
LEGACY_KIND='legacy-full48k-sha256'
COMMON_KIND='common-code44k-anchor-v1'
FAMILY_DOMAIN=b'VIMAR30805-LOADER-CODE44K-ANCHOR1\0'
LOADER_SIZE=0xc000
CODE_SIZE=0xb000
MAX_RECORDS=64

@dataclass(frozen=True)
class LoaderContractRecord:
    kind:str
    sha256:str
    def __post_init__(self):
        if type(self.kind) is not str or self.kind not in (LEGACY_KIND,COMMON_KIND):
            raise ValueError('unknown loader contract kind')
        if type(self.sha256) is not str or not re.fullmatch('[0-9a-f]{64}',self.sha256):
            raise ValueError('exact lowercase SHA256 required')
    def as_dict(self):return dict(kind=self.kind,sha256=self.sha256)


def measure_record(loader:bytes,kind:str)->LoaderContractRecord:
    if type(kind) is not str or kind not in (LEGACY_KIND,COMMON_KIND):
        raise ValueError('explicit known loader kind required')
    if type(loader) is not bytes or len(loader)!=LOADER_SIZE:
        raise ValueError('exact canonical48KiB loader image required')
    measured=loader if kind==LEGACY_KIND else FAMILY_DOMAIN+loader[:CODE_SIZE]
    return LoaderContractRecord(kind,hashlib.sha256(measured).hexdigest())


def validate_records(value)->tuple[LoaderContractRecord,...]:
    if type(value) is not list or not 1<=len(value)<=MAX_RECORDS:
        raise ValueError('one to64 explicit loader contract records required')
    result=[]
    for record in value:
        if type(record) is not dict or set(record)!={'kind','sha256'}:
            raise ValueError('unknown/missing loader contract fields')
        result.append(LoaderContractRecord(record['kind'],record['sha256']))
    keys=[(r.kind,r.sha256) for r in result]
    if keys!=sorted(set(keys)):
        raise ValueError('records must be unique and sorted by kind/SHA256')
    return tuple(result)


def canonical_records(records)->bytes:
    if type(records) not in (tuple,list) or not 1<=len(records)<=MAX_RECORDS or any(type(r) is not LoaderContractRecord for r in records):
        raise ValueError('bounded typed record sequence required')
    values=sorted((r.as_dict() for r in records),key=lambda r:(r['kind'],r['sha256']))
    validate_records(values)
    return (json.dumps(values,sort_keys=True,separators=(',',':'),ensure_ascii=True)+'\n').encode('ascii')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('loader',type=Path)
    parser.add_argument('--kind',required=True,choices=[LEGACY_KIND,COMMON_KIND])
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if not args.loader.is_file() or args.loader.stat().st_size!=LOADER_SIZE:
        parser.error('input must be an exact canonical48KiB regular artifact')
    with args.loader.open('rb') as file:data=file.read(LOADER_SIZE+1)
    result=canonical_records((measure_record(data,args.kind),))
    if args.output:
        destination=args.output.resolve()
        if destination.is_relative_to(ROOT/'inputs'):
            parser.error('output cannot modify immutable inputs')
        with destination.open('xb') as file:file.write(result)
    else:
        import sys
        sys.stdout.buffer.write(result)

if __name__=='__main__':main()
