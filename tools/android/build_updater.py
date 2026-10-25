#!/usr/bin/env python3
"""Build and audit the local Android release. Never prepares firmware or uses radio."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'apps/android-updater'
SDK = ROOT / 'work/android-sdk'
TOOLS = SDK / 'build-tools/35.0.0'
APP_VERSION = '1.0.1'
APP_VERSION_CODE = 21

def reserve_output(path):
    path.mkdir(parents=True, exist_ok=False)

def release_status():
    return {'hardware_validation':'not_performed',
            'android_instrumentation':'not_run_by_apk_build',
            'real_bundle':{'status':'not_assessed_by_apk_build','reason':'APK build does not assess firmware qualification or per-device package availability; consult the separately pinned firmware release evidence.'}}

def audit_manifest(badging, xml):
    if not re.search(r"(?m)^minSdkVersion:'26'$", badging) or not re.search(r"(?m)^targetSdkVersion:'35'$", badging):
        raise ValueError('Unexpected APK SDK: require min26/target35')
    # GitHub Releases is an approved online source; private firmware validation
    # and USB diagnostics remain local. Release APKs must stay non-debuggable.
    for forbidden in ('application-debuggable',):
        if forbidden in badging: raise ValueError('Forbidden APK manifest property: '+forbidden)
    if not re.search(r'android:allowBackup[^\n]*=false', xml): raise ValueError('Backup must be explicitly disabled')
    if f"versionName='{APP_VERSION}'" not in badging or f"versionCode='{APP_VERSION_CODE}'" not in badging:
        raise ValueError('Unexpected APK version')

def audit_entries(apk, public, fixture, anchor_path='res/raw/firmware_public.der'):
    with zipfile.ZipFile(apk) as z:
        names=z.namelist()
        if len(names)!=len(set(names)): raise ValueError('Duplicate APK entries')
        if anchor_path not in names or z.read(anchor_path) != public: raise ValueError('Release trust anchor mismatch')
        for name in names:
            data=z.read(name)
            # Published coroutines 1.10.2 ships one JVM class with a .bin name.
            approved_runtime_bin=(name=='DebugProbesKt.bin' and hashlib.sha256(data).hexdigest()==
                                  'cd3da36122413f84be484c77cde4a77729f9e8f81a285408d073300c8385ca3a')
            if (name.endswith(('.pem','.p12','.pfx','.jks','.keystore','.bin','.zip','.dat','.hex','.apk','.dump','.key')) and not approved_runtime_bin) or 'test-fixture' in name.lower():
                raise ValueError('Unexpected sensitive/firmware archive entry: '+name)
            if name.endswith('.der') and name!=anchor_path: raise ValueError('Unexpected DER key in APK')
            if re.search(rb'-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----', data): raise ValueError('Private key in APK')
            if fixture in data: raise ValueError('Synthetic fixture trust anchor in APK')
        return names

def run(args, log=None, cwd=ROOT, env=None):
    p=subprocess.run([str(x) for x in args],cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    if log: log.write_text(p.stdout)
    if p.returncode: raise RuntimeError('Command failed: '+str(args[0])+'; see '+str(log))
    return p.stdout

def signing_command(key, password, apk, aligned):
    # apksigner consumes password-file lines sequentially; omitting key-pass
    # correctly reuses the store password for this single-password identity.
    return [TOOLS/'apksigner','sign','--ks',key,'--ks-key-alias','vimar-updater',
            '--ks-pass','file:'+str(password),'--out',apk,aligned]

def test_totals(directory):
    suites=[ET.parse(p).getroot() for p in directory.glob('TEST-*.xml')]
    if not suites: raise ValueError('Missing test result XML: '+str(directory))
    totals={key:sum(int(s.get(key,'0')) for s in suites) for key in ('tests','failures','errors','skipped')}
    if totals['failures'] or totals['errors']: raise ValueError('Failed test suite')
    return totals

def anchor_resource_path(resources):
    matches=re.findall(r'raw/firmware_public\s*\n\s*\(\) \(file\) (\S+)',resources)
    if len(matches)!=1: raise ValueError('Missing/ambiguous public key resource')
    return matches[0]

def publish_verified(candidate, final, verifier):
    if final.exists(): raise FileExistsError(final)
    result=verifier(candidate)
    candidate.rename(final)
    return result

def audit_signed_apk(apk, output):
    cert=run([TOOLS/'apksigner','verify','--verbose','--print-certs',apk],output/'apksigner.txt')
    if 'Android Debug' in cert: raise ValueError('Debug signer')
    badging=run([TOOLS/'aapt2','dump','badging',apk],output/'aapt2-badging.txt')
    xml=run([TOOLS/'aapt2','dump','xmltree',apk,'--file','AndroidManifest.xml'],output/'aapt2-manifest.txt')
    audit_manifest(badging,xml)
    run(['openssl','pkey','-pubin','-in',ROOT/'firmware/keys/dev-public.pem','-outform','DER','-out',output/'expected-public.der'],output/'public-conversion.log')
    public=(output/'expected-public.der').read_bytes()
    resources=run([TOOLS/'aapt2','dump','resources',apk],output/'aapt2-resources.txt')
    entries=audit_entries(apk,public,(APP/'test-fixtures/synthetic-public.der').read_bytes(),anchor_resource_path(resources))
    with zipfile.ZipFile(apk) as archive:
        if archive.read('assets/third_party_notices.txt') != (ROOT/'THIRD_PARTY_NOTICES.md').read_bytes():
            raise ValueError('Packaged notices differ from release notices')
    (output/'expected-public.der').unlink()
    return entries, public


def build(output):
    output = output.resolve()
    root = ROOT.resolve()
    if not output.is_relative_to(root):
        raise ValueError('Output must be inside the repository')
    if output.is_relative_to((root / 'inputs').resolve()):
        raise ValueError('Output must not be inside immutable inputs')
    reserve_output(output)
    env=os.environ.copy()
    env.update(ANDROID_HOME=str(SDK),ANDROID_SDK_ROOT=str(SDK),GRADLE_USER_HOME=str(ROOT/'work/android-gradle-cache'))
    tasks=[':core:test',':app:testDebugUnitTest',':app:lint',':app:assembleRelease']
    run([APP/'gradlew','--offline','--dependency-verification=strict',*tasks],output/'gradle.log',APP,env)
    private=ROOT/'work/private/android-updater'
    private.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(private,0o700)
    password=private/'signing-password.txt'; key=private/'signing.jks'
    if key.exists()!=password.exists(): raise RuntimeError('Incomplete existing signing identity; refusing replacement')
    if not key.exists():
        fd=os.open(password,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f: f.write(secrets.token_urlsafe(48)+'\n')
        run(['keytool','-genkeypair','-keystore',key,'-storepass:file',password,'-keypass:file',password,'-alias','vimar-updater','-keyalg','RSA','-keysize','3072','-validity','10000','-dname','CN=Vimar Updater Local Release'],output/'key-generation.log')
    os.chmod(key,0o600); os.chmod(password,0o600)
    unsigned=APP/'app/build/outputs/apk/release/app-release-unsigned.apk'
    aligned=output/'aligned-unsigned.apk'
    run([TOOLS/'zipalign','-p','-f','4',unsigned,aligned],output/'zipalign.log')
    apk=output/'candidate.apk'
    run(signing_command(key,password,apk,aligned),output/'signing.log')
    aligned.unlink()
    final=output/f'vimar-updater-{APP_VERSION}.apk'
    entries,public=publish_verified(apk,final,lambda candidate:audit_signed_apk(candidate,output))
    apk=final
    digest=hashlib.sha256(apk.read_bytes()).hexdigest()
    (output/'SHA256SUMS').write_text(digest+'  '+apk.name+'\n')
    report=release_status()
    report.update(tests={'core':test_totals(APP/'core/build/test-results/test'),'app':test_totals(APP/'app/build/test-results/testDebugUnitTest')},apk=str(apk.relative_to(ROOT)),sha256=digest,software_checks='passed',tasks=tasks,
                  entry_count=len(entries),trust_anchor_sha256=hashlib.sha256(public).hexdigest(),
                  toolchain={'sdk':35,'build_tools':'35.0.0','gradle':'8.11.1','agp':'8.10.1','kotlin':'2.2.20'},
                  notices_sha256=hashlib.sha256((ROOT/'THIRD_PARTY_NOTICES.md').read_bytes()).hexdigest())
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=ROOT/'experiments/android-updater/builds'/APP_VERSION/datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d_%H-%M-%S.%fZ'))
    args=p.parse_args()
    print(json.dumps(build(args.output.resolve()),indent=2))

if __name__=='__main__': main()
