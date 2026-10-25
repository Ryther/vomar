"""Promote an exact signed qualification candidate after matching physical evidence.

Only outer metadata changes. No image, loader, carrier or device memory is built
or modified. The authoritative existing qualified producer signs the result.
"""
import argparse,json,tempfile
from pathlib import Path
import zipfile,io
from tools.firmware.package_common_android_update_v3 import _validate_common_v3_bundle,load_public_key,create_common_v3_bundle,ROLES,FILES,strict_json,sha
from .signers import verify_firmware_identity
ROOT=Path(__file__).resolve().parents[2]

def promote(candidate,qualification,output,private_key,public_key):
    identities=json.loads((ROOT/'tools/release/signing-identities.json').read_text());verify_firmware_identity(private_key,public_key,identities['firmwarePublicKeySha256'])
    raw=Path(candidate).read_bytes();m=_validate_common_v3_bundle(raw,load_public_key(public_key),expected_purpose='qualification-candidate')
    with tempfile.TemporaryDirectory(prefix='vomar-trusted-promote-') as d:
        d=Path(d)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:entries={n:z.read(n) for n in z.namelist()}
        q=Path(qualification).read_bytes();(d/'qualification.json').write_bytes(q)
        descriptor={k:v for k,v in m.items() if k not in {'bundleId','purpose','qualificationSha256','firstInstall',*ROLES,'zigbeeOta'}}
        for role in ROLES:
            if role in m:
                name=FILES[role];(d/name).write_bytes(entries[name]);descriptor[role]={'path':name,'sha256':sha(entries[name])}
        for role,name in [('loader','loader.bin'),('zigbeeOta','main.ota')]:
            if name in entries:(d/name).write_bytes(entries[name]);descriptor[role]={'path':name,'sha256':sha(entries[name])}
        descriptor['qualification']={'path':'qualification.json','sha256':sha(q)}
        first=strict_json(entries['first-install.json'])
        if 'watchdogHandoff' in first:descriptor['watchdogHandoff']=first['watchdogHandoff']
        path=d/'release.json';path.write_text(json.dumps(descriptor));return create_common_v3_bundle(path,output,private_key,public_key)
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('candidate','qualification','output','private-key','public-key'):p.add_argument('--'+name,type=Path,required=True)
 print(json.dumps(promote(**vars(p.parse_args())),indent=2))
