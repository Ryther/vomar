"""Generate synthetic Android-only fixtures; temporary private key is never written."""
import hashlib
import json
from pathlib import Path
import zipfile
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

root = Path(__file__).resolve().parent
source = root.parents[2] / 'test-fixtures' / 'synthetic-update.zip'
key = ec.generate_private_key(ec.SECP256R1())
(root / 'assets' / 'synthetic-public.der').write_bytes(key.public_key().public_bytes(
    serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo))
with zipfile.ZipFile(source) as archive:
    entries = {name: archive.read(name) for name in archive.namelist()}

def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode()

for number, filename in enumerate(('synthetic-update.zip', 'synthetic-second.zip')):
    manifest = json.loads(entries['manifest.json'])
    if number:
        manifest['device']['name'] = 'Synthetic second dimmer'
        manifest['device']['bleAddress'] = 'AA:BB:CC:DD:EE:02'
        manifest['device']['ieee'] = '0123456789abcd02'
        manifest['device']['uid'] = ['12345678', 'abcdef02']
    del manifest['bundleId']
    manifest['bundleId'] = hashlib.sha256(canonical(manifest)).hexdigest()
    data = canonical(manifest)
    with zipfile.ZipFile(root / 'assets' / filename, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, contents in entries.items():
            if name == 'manifest.json': contents = data
            if name == 'manifest.sig': contents = key.sign(data, ec.ECDSA(hashes.SHA256()))
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, contents)
