"""Public DK compile lane using an explicitly ephemeral development signer."""
import argparse
import os
import json
from pathlib import Path
import subprocess
import tempfile
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
ROOT=Path(__file__).resolve().parents[2]

def firmware_version():
    import re
    text=(ROOT/'firmware/VERSION').read_text();return '.'.join(re.search(name+r'\s*=\s*([0-9]+)',text)[1] for name in ('VERSION_MAJOR','VERSION_MINOR','PATCHLEVEL'))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.absolute();out.mkdir(parents=True,exist_ok=True)
    ws=Path(os.environ['VIMAR_NCS_WORKSPACE']);west=Path(os.environ['VIMAR_WEST'])
    with tempfile.TemporaryDirectory(prefix='vomar-ci-development-key-') as d:
        identity=ec.generate_private_key(ec.SECP256R1());key=Path(d)/'ephemeral.pem';key.write_bytes(identity.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));key.chmod(0o600)
        public=Path(d)/'public.pem';public.write_bytes(identity.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
        for name,extra in [('zigbee',['-DEXTRA_CONF_FILE=zigbee_dk.conf']),('ota',['-DFILE_SUFFIX=ota'])]:
            subprocess.run([str(west),'build','--sysbuild','-b','nrf52840dk/nrf52840',str(ROOT/'firmware'),'--pristine','-d',str(out/name),'--','-DSB_CONFIG_BOOT_SIGNATURE_KEY_FILE="'+str(key)+'"','-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',*extra],cwd=ws,check=True)
        registry=Path(d)/'synthetic-legacy.json';registry.write_text(json.dumps({'allowed_loaders':['0'*64,'1'*64,'2'*64]}))
        policy=Path(d)/'synthetic-source.json';policy.write_text(json.dumps({'allowedSourceSignedHashes':['3'*64],'legacyRecoverySignedHashes':['4'*64]}))
        env={**os.environ,'VIMAR_SIGNING_PRIVATE_KEY':str(key),'VIMAR_SIGNING_PUBLIC_KEY':str(public),'CMAKE_EXPORT_COMPILE_COMMANDS':'ON'}
        subprocess.run([os.environ['VIMAR_BUILD_PYTHON'],'-m','tools.firmware.build_typed_common_candidate','--output',str(out/'typed'),'--legacy-registry',str(registry),'--source-policy',str(policy),'--watchdog-handoff','paused-reset-before-main-v1','--multi-bond','--release-version',firmware_version()],cwd=ROOT,env=env,check=True)
    print('DK compile only. Ephemeral signer; no official release or physical qualification.')
if __name__=='__main__':main()
