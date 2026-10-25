"""Trusted asset assembly from exact-run artifacts; no candidate code execution."""
from __future__ import annotations
import argparse
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import zipfile
from cryptography.hazmat.primitives import serialization
from .manifest import build_manifest,digest,loads
from .promote_firmware import promote
from .signers import sign_android
from tools.android.build_updater import audit_entries,audit_manifest,anchor_resource_path

ROOT=Path(__file__).resolve().parents[2]


def android_owner(source):
    version=re.findall(r'versionName="([0-9]+\.[0-9]+\.[0-9]+)"',source)
    code=re.findall(r'versionCode=([0-9]+)',source)
    if len(version)!=1 or len(code)!=1:raise ValueError('Ambiguous native Android version owner')
    return version[0],int(code[0])


def audit_apk(path,tools,version,code):
    def capture(*args):return subprocess.run([str(Path(tools)/args[0]),*map(str,args[1:])],check=True,capture_output=True,text=True).stdout
    audit_manifest(capture('aapt2','dump','badging',path),capture('aapt2','dump','xmltree',path,'--file','AndroidManifest.xml'),version,code)
    key=serialization.load_pem_public_key((ROOT/'firmware/keys/dev-public.pem').read_bytes()).public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    resource=anchor_resource_path(capture('aapt2','dump','resources',path))
    audit_entries(path,key,(ROOT/'apps/android-updater/test-fixtures/synthetic-public.der').read_bytes(),resource)
    with zipfile.ZipFile(path) as z:
        if z.read('assets/third_party_notices.txt')!=(ROOT/'THIRD_PARTY_NOTICES.md').read_bytes():raise ValueError('APK notices mismatch')


def assemble(inputs,output,version,sha,firmware_candidate,qualification,private_key,keystore,password_file,android_tools):
    if not re.fullmatch('[0-9a-f]{40}',sha):raise ValueError('Exact source SHA required')
    output=Path(output);output.mkdir(parents=True,exist_ok=False);inputs=Path(inputs)
    # Versions come from native source owners exported by the credential-free
    # build lane; publisher independently checks the exact source SHA/checks.
    source=loads((inputs/'component-versions.json').read_bytes())
    if source.get('distributionVersion')!=version:raise ValueError('Distribution version differs from the exact candidate VERSION')
    if source.get('commit')!=sha:raise ValueError('Component metadata belongs to another source revision')
    av=source['android']['version'];ac=source['android']['versionCode'];dv=source['desktop']['version'];zv=source['zigbee2mqtt']['version']
    if loads(Path(qualification).read_bytes()).get('sourceCommit')!=sha:raise ValueError('Protected physical evidence must name the exact source commit')
    identities=loads((ROOT/'tools/release/signing-identities.json').read_bytes())
    unsigned=inputs/'app-release-unsigned.apk';audit_apk(unsigned,android_tools,av,ac)
    apk=output/f'vomar-android-{version}.apk';sign_android(unsigned,apk,sdk_tools=android_tools,keystore=keystore,password_file=password_file,identities=identities);audit_apk(apk,android_tools,av,ac)
    firmware=output/f'vomar-firmware-{version}.zip';promote(firmware_candidate,qualification,firmware,private_key,ROOT/'firmware/keys/dev-public.pem')
    with zipfile.ZipFile(firmware) as z:
        m=loads(z.read('manifest.json'));ota=output/f'vomar-firmware-{version}.ota';ota.write_bytes(z.read('main.ota'))
    records=[{'role':'firmware-common','filename':firmware.name,'componentVersion':m['main']['version']},{'role':'zigbee-ota','filename':ota.name,'componentVersion':m['main']['version']},{'role':'android-apk','filename':apk.name,'componentVersion':av,'androidVersionCode':ac}]
    for platform,arch,extension in [('linux','x64','tar.gz'),('windows','x64','zip'),('macos','x64','dmg'),('macos','arm64','dmg')]:
        name=f'vomar-desktop-{version}-{platform}-{arch}.{extension}';path=inputs/name
        if not path.is_file() or path.is_symlink():raise ValueError('Missing native platform artifact: '+name)
        shutil.copy2(path,output/name);records.append({'role':f'desktop-{platform}-{arch}','filename':name,'componentVersion':dv,'platform':platform,'architecture':arch})
    setup=f'vomar-desktop-{version}-windows-x64-setup.exe'
    if not (inputs/setup).is_file():raise ValueError('Missing per-user Windows installer')
    shutil.copy2(inputs/setup,output/setup);records.append({'role':'desktop-windows-setup','filename':setup,'componentVersion':dv,'platform':'windows','architecture':'x64'})
    for role,name,src,component in [('zigbee2mqtt-converter',f'vomar-zigbee2mqtt-{version}.js',inputs/'vimar_30805.js',zv),('licenses',f'vomar-notices-{version}.txt',ROOT/'THIRD_PARTY_NOTICES.md',version),('offline-guide',f'vomar-installation-{version}.md',ROOT/'docs/offline-guide.md',version)]:
        shutil.copy2(src,output/name);records.append({'role':role,'filename':name,'componentVersion':component})
    manifest=build_manifest(version,sha,records,output,{'firmware':m['main']['version'],'android':av,'desktop':dv,'zigbee2mqtt':zv})
    (output/'release-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    names=sorted(a['filename'] for a in records)+['release-manifest.json']
    (output/'SHA256SUMS').write_text(''.join(digest((output/name).read_bytes())+'  '+name+'\n' for name in sorted(names)))
    return manifest

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('inputs','output','firmware-candidate','qualification','private-key','keystore','password-file','android-tools'):p.add_argument('--'+name,type=Path,required=True)
 p.add_argument('--version',required=True);p.add_argument('--sha',required=True);print(json.dumps(assemble(**vars(p.parse_args())),indent=2))
