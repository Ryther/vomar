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


def candidate_metadata(path):
    from tools.firmware.package_common_android_update_v3 import _validate_common_v3_bundle,load_public_key
    return _validate_common_v3_bundle(Path(path).read_bytes(),load_public_key(ROOT/'firmware/keys/dev-public.pem'),expected_purpose='qualification-candidate')


def write_metadata(output,manifest):
    (output/'release-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    names=sorted(a['filename'] for a in manifest['artifacts'])+['release-manifest.json']
    (output/'SHA256SUMS').write_text(''.join(digest((output/name).read_bytes())+'  '+name+'\n' for name in sorted(names)))


def finalize_acceptance(directory,acceptance):
    from .evidence import owner_acceptance,require_manual_acceptance
    require_manual_acceptance()
    from .manifest import validate
    directory=Path(directory);manifest=validate(loads((directory/'release-manifest.json').read_bytes()),directory)
    version=manifest['distributionVersion'];assets={a['role']:a for a in manifest['artifacts']}
    if assets['firmware-common']['filename']!=f'vomar-firmware-{version}-qualification-candidate.zip' or assets['zigbee-ota']['filename']!=f'vomar-firmware-{version}-qualification-candidate.ota':
        raise ValueError('Only an explicitly staged experimental distribution can be finalized')
    metadata=candidate_metadata(directory/assets['firmware-common']['filename'])
    if metadata['main']['version']!=manifest['components']['firmware']:raise ValueError('Firmware version differs from staged source owner')
    raw=Path(acceptance).read_bytes();owner_acceptance(manifest,loads(raw))
    name=f'vomar-release-acceptance-{version}.json';path=directory/name
    if 'release-acceptance' in assets:
        if assets['release-acceptance']['filename']!=name or path.read_bytes()!=raw:raise ValueError('Finalized owner acceptance differs; stage a new candidate')
        write_metadata(directory,manifest)
        return manifest
    if path.is_symlink() or path.exists() and (not path.is_file() or path.read_bytes()!=raw):raise ValueError('Unreviewed acceptance path already exists')
    if not path.exists():
        with path.open('xb') as stream:stream.write(raw)
    manifest['artifacts'].append({'role':'release-acceptance','filename':name,'componentVersion':version,'size':len(raw),'sha256':digest(raw)})
    manifest['artifacts'].sort(key=lambda a:a['role']);validate(manifest,directory);write_metadata(directory,manifest)
    return manifest


def assemble(inputs,output,version,sha,firmware_candidate,qualification,private_key,keystore,password_file,android_tools,*,accepted_with_known_issues=False):
    if accepted_with_known_issues:
        from .evidence import require_manual_acceptance
        require_manual_acceptance()
    if not re.fullmatch('[0-9a-f]{40}',sha):raise ValueError('Exact source SHA required')
    output=Path(output);output.mkdir(parents=True,exist_ok=False);inputs=Path(inputs)
    # Versions come from native source owners exported by the credential-free
    # build lane; publisher independently checks the exact source SHA/checks.
    source=loads((inputs/'component-versions.json').read_bytes())
    if source.get('distributionVersion')!=version:raise ValueError('Distribution version differs from the exact candidate VERSION')
    if source.get('commit')!=sha:raise ValueError('Component metadata belongs to another source revision')
    av=source['android']['version'];ac=source['android']['versionCode'];dv=source['desktop']['version'];zv=source['zigbee2mqtt']['version']
    if not accepted_with_known_issues:
        if qualification is None or loads(Path(qualification).read_bytes()).get('sourceCommit')!=sha:raise ValueError('Protected physical evidence must name the exact source commit')
        if private_key is None:raise ValueError('Existing firmware signer required for qualified promotion')
    identities=loads((ROOT/'tools/release/signing-identities.json').read_bytes())
    unsigned=inputs/'app-release-unsigned.apk';audit_apk(unsigned,android_tools,av,ac)
    apk=output/f'vomar-android-{version}.apk';sign_android(unsigned,apk,sdk_tools=android_tools,keystore=keystore,password_file=password_file,identities=identities);audit_apk(apk,android_tools,av,ac)
    suffix='-qualification-candidate' if accepted_with_known_issues else ''
    firmware=output/f'vomar-firmware-{version}{suffix}.zip'
    if accepted_with_known_issues:
        candidate_metadata(firmware_candidate)
        firmware.write_bytes(Path(firmware_candidate).read_bytes())
    else:promote(firmware_candidate,qualification,firmware,private_key,ROOT/'firmware/keys/dev-public.pem')
    with zipfile.ZipFile(firmware) as z:
        m=loads(z.read('manifest.json'))
        if m['main']['version']!=source['firmware']['version']:raise ValueError('Firmware version differs from its native source owner')
        ota=output/f'vomar-firmware-{version}{suffix}.ota';ota.write_bytes(z.read('main.ota'))
    records=[{'role':'firmware-common','filename':firmware.name,'componentVersion':m['main']['version']},{'role':'zigbee-ota','filename':ota.name,'componentVersion':m['main']['version']},{'role':'android-apk','filename':apk.name,'componentVersion':av,'androidVersionCode':ac}]
    for platform,arch,extension in [('linux','x64','tar.gz'),('windows','x64','zip'),('macos','arm64','dmg')]:
        name=f'vomar-desktop-{version}-{platform}-{arch}.{extension}';path=inputs/name
        if not path.is_file() or path.is_symlink():raise ValueError('Missing native platform artifact: '+name)
        shutil.copy2(path,output/name);records.append({'role':f'desktop-{platform}-{arch}','filename':name,'componentVersion':dv,'platform':platform,'architecture':arch})
    setup=f'vomar-desktop-{version}-windows-x64-setup.exe'
    if not (inputs/setup).is_file():raise ValueError('Missing per-user Windows installer')
    shutil.copy2(inputs/setup,output/setup);records.append({'role':'desktop-windows-setup','filename':setup,'componentVersion':dv,'platform':'windows','architecture':'x64'})
    for role,name,src,component in [('zigbee2mqtt-converter',f'vomar-zigbee2mqtt-{version}.js',inputs/'vimar_30805.js',zv),('licenses',f'vomar-notices-{version}.txt',ROOT/'THIRD_PARTY_NOTICES.md',version),('offline-guide',f'vomar-installation-{version}.md',ROOT/'docs/offline-guide.md',version)]:
        shutil.copy2(src,output/name);records.append({'role':role,'filename':name,'componentVersion':component})
    from .evidence import DEPENDENCY_GRAPHS
    inventory=output/f'vomar-dependency-inventories-{version}.zip'
    with zipfile.ZipFile(inventory,'x',zipfile.ZIP_STORED) as archive:
        for graph in sorted(DEPENDENCY_GRAPHS):
            raw=(inputs/(graph+'.json')).read_bytes();data=loads(raw)
            if data.get('sourceCommit')!=sha or data.get('graph')!=graph or not 1<=len(raw)<=8*1024*1024:raise ValueError('Missing or mismatched delivered inventory: '+graph)
            archive.writestr(zipfile.ZipInfo(graph+'.json',(2020,1,1,0,0,0)),raw)
    records.append({'role':'source-sbom','filename':inventory.name,'componentVersion':version})
    manifest=build_manifest(version,sha,records,output,{'firmware':m['main']['version'],'android':av,'desktop':dv,'zigbee2mqtt':zv})
    write_metadata(output,manifest)
    return manifest

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--finalize-accepted',type=Path,metavar='STAGED_DIRECTORY');p.add_argument('--acceptance',type=Path)
 p.add_argument('--accepted-with-known-issues',action='store_true',help='Explicitly stage experimental firmware unchanged; owner acceptance is a separate final step')
 for name in ('inputs','output','firmware-candidate','qualification','private-key','keystore','password-file','android-tools'):p.add_argument('--'+name,type=Path)
 p.add_argument('--version');p.add_argument('--sha');a=vars(p.parse_args())
 staged=a.pop('finalize_accepted');acceptance=a.pop('acceptance')
 if staged:
  if not acceptance:p.error('--finalize-accepted requires --acceptance')
  print(json.dumps(finalize_acceptance(staged,acceptance),indent=2))
 else:
  if acceptance:p.error('--acceptance is only used with --finalize-accepted')
  for name in ('inputs','output','firmware_candidate','keystore','password_file','android_tools','version','sha'):
   if a[name] is None:p.error('--'+name.replace('_','-')+' is required for staging')
  print(json.dumps(assemble(**a),indent=2))
