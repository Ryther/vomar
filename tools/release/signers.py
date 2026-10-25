"""Explicit existing signer verification. No identity generation or hardware I/O."""
import hashlib
from pathlib import Path
import re
import subprocess
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def verify_firmware_identity(private_path, public_path, expected_sha256):
    private_path=Path(private_path);public_path=Path(public_path)
    if not private_path.is_file() or not public_path.is_file():raise ValueError('Existing explicit firmware signing identity required')
    private=serialization.load_pem_private_key(private_path.read_bytes(),password=None)
    if not isinstance(private,ec.EllipticCurvePrivateKey) or not isinstance(private.curve,ec.SECP256R1):raise ValueError('P256 firmware identity required')
    der=private.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    public=serialization.load_pem_public_key(public_path.read_bytes()).public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    if der!=public or hashlib.sha256(der).hexdigest()!=expected_sha256:raise ValueError('Firmware signer continuity mismatch')
    return expected_sha256


def verify_android_identity(keystore,password_file,expected_sha256,alias='vimar-updater'):
    if not expected_sha256 or not re.fullmatch('[0-9a-f]{64}',expected_sha256):raise ValueError('Pinned Android signer fingerprint required')
    if not Path(keystore).is_file() or not Path(password_file).is_file():raise ValueError('Existing Android signer required; automatic generation forbidden')
    r=subprocess.run(['keytool','-exportcert','-keystore',str(keystore),'-storepass:file',str(password_file),'-alias',alias],check=True,capture_output=True)
    if hashlib.sha256(r.stdout).hexdigest()!=expected_sha256:raise ValueError('Android signer continuity mismatch')
    return expected_sha256


def sign_android(unsigned, output, *, sdk_tools, keystore, password_file, identities):
    """Sign only explicitly supplied unsigned bytes with the pinned existing signer."""
    verify_android_identity(keystore,password_file,identities['androidCertificateSha256'],identities['androidAlias'])
    output=Path(output)
    if output.exists():raise FileExistsError(output)
    import tempfile
    with tempfile.TemporaryDirectory(prefix='vomar-apk-sign-') as d:
        aligned=Path(d)/'aligned.apk'
        subprocess.run([str(Path(sdk_tools)/'zipalign'),'-p','4',str(unsigned),str(aligned)],check=True,capture_output=True)
        candidate=Path(d)/'signed.apk'
        subprocess.run([str(Path(sdk_tools)/'apksigner'),'sign','--ks',str(keystore),'--ks-key-alias',identities['androidAlias'],'--ks-pass','file:'+str(password_file),'--out',str(candidate),str(aligned)],check=True,capture_output=True)
        report=subprocess.run([str(Path(sdk_tools)/'apksigner'),'verify','--verbose','--print-certs',str(candidate)],check=True,capture_output=True,text=True).stdout
        match=re.search(r'Signer #1 certificate SHA-256 digest: ([0-9a-fA-F]+)',report)
        if not match or match[1].lower()!=identities['androidCertificateSha256']:raise ValueError('Signed APK certificate mismatch')
        # Exclusive output creation; an interrupted signer never replaces an asset.
        with output.open('xb') as f:f.write(candidate.read_bytes())
    return output
