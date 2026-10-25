"""Common release ZIP contract: generated keys and synthetic signed images only."""
import hashlib
import json
import lzma
import struct
import zipfile

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def signed_image(key, role=1, profile=2, damage=False):
    payload = struct.pack('<II', 0x20010000, 0xc201) + bytes(56)
    target = b'VIMAR30805' + bytes([profile])
    fields = struct.pack('<HH', 0xa0, len(target)) + target + struct.pack('<HHB', 0xa1, 1, role)
    protected = struct.pack('<HH', 0x6908, len(fields) + 4) + fields
    header = bytearray(512)
    struct.pack_into('<I', header, 0, 0x96f3b83d)
    struct.pack_into('<HHII', header, 8, 512, len(protected), len(payload), 0)
    struct.pack_into('<BBHI', header, 20, 0, 6, 0, 0)
    region = bytes(header) + payload + protected
    digest = hashlib.sha256(region).digest()
    signature = key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    if damage:
        signature = signature[:-1] + bytes([signature[-1] ^ 1])
    keyhash = hashlib.sha256(key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).digest()
    fields = struct.pack('<HH', 1, 32) + keyhash + struct.pack('<HH', 0x10, 32) + digest + struct.pack('<HH', 0x22, len(signature)) + signature
    return region + struct.pack('<HH', 0x6907, len(fields) + 4) + fields


@pytest.fixture
def release(tmp_path):
    from tools.firmware.ota_release import REQUIRED_CHECKS, SPLIT_REQUIRED_CHECKS
    key = ec.generate_private_key(ec.SECP256R1())
    private = tmp_path / 'test-key.pem'
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public = tmp_path / 'test-public.pem'
    public.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    blob = signed_image(key)
    (tmp_path / 'main.signed.bin').write_bytes(blob)
    qualification = dict(schemaVersion=2, model='VIMAR30805', layoutVersion=2,
                         allowedLoaderSha256=['a' * 64], components={'main': sha(blob)},
                         **{field: True for field in (*REQUIRED_CHECKS, *SPLIT_REQUIRED_CHECKS)})
    qpath = tmp_path / 'qualification.json'
    qpath.write_text(json.dumps(qualification))
    descriptor = dict(schemaVersion=2, minAppVersion='0.3.0', model='VIMAR30805', layoutVersion=2,
                      identityProtocol=1, allowedLoaderSha256=['a' * 64], legacyRecoverySignedHashes=[],
                      targetRecoverySignedHash='b' * 64, allowedSourceSignedHashes=['c' * 64],
                      main=dict(path='main.signed.bin', sha256=sha(blob)),
                      qualification=dict(path=qpath.name, sha256=sha(qpath.read_bytes())))
    path = tmp_path / 'release.json'
    path.write_text(json.dumps(descriptor))
    return dict(release=path, private_key=private, public_key=public, output=tmp_path / 'common.zip'), key


def package(args):
    from tools.firmware.package_common_android_update import create_common_update_bundle
    return create_common_update_bundle(**args)

def attach_ota(args,key,damage=None):
    main=(args['release'].parent/'main.signed.bin').read_bytes()
    from tools.firmware.package_zigbee_ota import image
    parsed=image(main);end=parsed['authenticated_end'];size=parsed['size']
    payload=main[512:512+size]
    stream=b'\x06\x5d'+lzma.compress(payload,format=lzma.FORMAT_RAW,filters=[{'id':lzma.FILTER_ARMTHUMB},{'id':lzma.FILTER_LZMA2,'dict_size':32768}])
    inner=parsed['unprotected'][0x22]
    fields=b''.join(struct.pack('<HH',tag,len(value))+value for tag,value in [
        (0x70,struct.pack('<I',size)),(0x71,bytes.fromhex(sha(main[:end]))),(0x72,inner),
        (0xa0,b'VIMAR30805\x02'),(0xa1,b'\x01')])
    protected=struct.pack('<HH',0x6908,len(fields)+4)+fields
    header=bytearray(main[:512]);struct.pack_into('<H',header,10,len(protected));struct.pack_into('<II',header,12,len(stream),0xc00)
    region=bytes(header)+stream+protected
    if damage=='decoded':
        corrupt=bytearray(payload);corrupt[20]^=1
        stream=b'\x06\x5d'+lzma.compress(bytes(corrupt),format=lzma.FORMAT_RAW,filters=[{'id':lzma.FILTER_ARMTHUMB},{'id':lzma.FILTER_LZMA2,'dict_size':32768}])
        struct.pack_into('<I',header,12,len(stream));region=bytes(header)+stream+protected
    digest=hashlib.sha256(region).digest();signature=key.sign(digest,ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    keyhash=parsed['unprotected'][1]
    entries=struct.pack('<HH',1,32)+keyhash+struct.pack('<HH',0x10,32)+digest+struct.pack('<HH',0x22,len(signature))+signature
    compressed=region+struct.pack('<HH',0x6907,len(entries)+4)+entries
    total=66+len(compressed)
    ota=struct.pack('<IHHHHHIH32sIHHHI',0x0beef11e,0x100,60,4,0xfff1,0x3085,0x00060000,2,b'Vimar30805 signed compressed OTA',total,1,1,0,len(compressed))+compressed
    if damage=='header':ota=ota[:10]+b'\x00\x00'+ota[12:]
    path=args['release'].parent/'main.ota';path.write_bytes(ota)
    desc=json.loads(args['release'].read_text());desc['zigbeeOta']={'path':'main.ota','sha256':sha(ota)}
    qpath=args['release'].parent/'qualification.json';q=json.loads(qpath.read_text());q['components']['zigbeeOta']=sha(ota)
    qpath.write_text(json.dumps(q));desc['qualification']['sha256']=sha(qpath.read_bytes());args['release'].write_text(json.dumps(desc))
    return ota

def test_optional_zigbee_carrier_is_publisher_bound_to_exact_main_and_qualification(release):
    args,key=release;ota=attach_ota(args,key);package(args)
    with zipfile.ZipFile(args['output']) as archive:
        manifest=json.loads(archive.read('manifest.json'));meta=manifest['zigbeeOta']
        assert archive.read('main.ota')==ota
        assert meta==dict(file='main.ota',size=len(ota),fileSha256=sha(ota),manufacturerCode=0xfff1,imageType=0x3085,
                         fileVersion=0x00060000,model='VIMAR30805',profile=2,mainSignedRegionSha256=manifest['main']['signedRegionSha256'])
        key.public_key().verify(archive.read('manifest.sig'),archive.read('manifest.json'),ec.ECDSA(hashes.SHA256()))

@pytest.mark.parametrize('damage',['decoded','header','unqualified'])
def test_signed_but_wrong_or_unqualified_carrier_rejected(release,damage):
    args,key=release;attach_ota(args,key,damage)
    if damage=='unqualified':
        desc=json.loads(args['release'].read_text());qpath=args['release'].parent/'qualification.json'
        q=json.loads(qpath.read_text());del q['components']['zigbeeOta'];qpath.write_text(json.dumps(q));desc['qualification']['sha256']=sha(qpath.read_bytes());args['release'].write_text(json.dumps(desc))
    with pytest.raises(ValueError):package(args)
    assert not args['output'].exists()


def test_common_zip_has_no_per_device_identity_and_authenticates_main_role(release):
    args, key = release
    result = package(args)
    with zipfile.ZipFile(args['output']) as archive:
        assert archive.namelist() == ['manifest.json', 'manifest.sig', 'main.signed.bin']
        raw = archive.read('manifest.json')
        key.public_key().verify(archive.read('manifest.sig'), raw, ec.ECDSA(hashes.SHA256()))
        manifest = json.loads(raw)
        assert manifest['schemaVersion'] == 2
        assert manifest['main']['role'] == 'MAIN'
        assert manifest['main']['version'] == '0.6.0'
        assert not ({'device', 'uid', 'ieee', 'bleAddress', 'name'} & set(manifest))
        assert b'PRIVATE KEY' not in b''.join(archive.read(n) for n in archive.namelist())
        assert manifest['main']['fileSha256'] == sha(archive.read('main.signed.bin'))
        assert result['bundleId'] == manifest['bundleId']
    assert result['sha256'] == sha(args['output'].read_bytes())


@pytest.mark.parametrize('damage', ['role', 'profile', 'signature', 'qualification', 'loader', 'device', 'unknown'])
def test_invalid_common_release_is_rejected_before_output(release, damage):
    args, key = release
    descriptor = json.loads(args['release'].read_text())
    if damage in ('role', 'profile', 'signature'):
        blob = signed_image(key, role=4 if damage == 'role' else 1,
                            profile=1 if damage == 'profile' else 2, damage=damage == 'signature')
        (args['release'].parent / 'main.signed.bin').write_bytes(blob)
        descriptor['main']['sha256'] = sha(blob)
        qpath = args['release'].parent / 'qualification.json'
        q = json.loads(qpath.read_text()); q['components']['main'] = sha(blob)
        qpath.write_text(json.dumps(q)); descriptor['qualification']['sha256'] = sha(qpath.read_bytes())
    if damage == 'qualification':
        qpath = args['release'].parent / 'qualification.json'
        q = json.loads(qpath.read_text()); q['power_cut_recovery_verified'] = False
        qpath.write_text(json.dumps(q)); descriptor['qualification']['sha256'] = sha(qpath.read_bytes())
    if damage == 'loader': descriptor['allowedLoaderSha256'] = ['d' * 64]
    if damage == 'device': descriptor['device'] = {'uid': ['00000001', '00000002']}
    if damage == 'unknown': descriptor['bypassQualification'] = True
    args['release'].write_text(json.dumps(descriptor))
    with pytest.raises(ValueError): package(args)
    assert not args['output'].exists()


def test_common_packager_never_overwrites(release):
    args, _ = release
    args['output'].write_bytes(b'preserve')
    with pytest.raises(ValueError): package(args)
    assert args['output'].read_bytes() == b'preserve'


def test_generic_migration_is_one_shared_role_authenticated_component(release):
    args, key = release
    descriptor = json.loads(args['release'].read_text())
    blob = signed_image(key, role=3)
    (args['release'].parent / 'migration.signed.bin').write_bytes(blob)
    descriptor['migration'] = dict(path='migration.signed.bin', sha256=sha(blob))
    descriptor['legacyRecoverySignedHashes'] = ['d' * 64]
    qpath = args['release'].parent / 'qualification.json'
    q = json.loads(qpath.read_text()); q['components']['migration'] = sha(blob)
    qpath.write_text(json.dumps(q)); descriptor['qualification']['sha256'] = sha(qpath.read_bytes())
    args['release'].write_text(json.dumps(descriptor))
    package(args)
    with zipfile.ZipFile(args['output']) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['migration']['role'] == 'MIGRATION'
        assert archive.read('migration.signed.bin') == blob
        assert b'uid' not in archive.read('manifest.json')


def test_legacy_recovery_allowlist_without_migration_is_rejected(release):
    args, _ = release
    descriptor = json.loads(args['release'].read_text())
    descriptor['legacyRecoverySignedHashes'] = ['d' * 64]
    args['release'].write_text(json.dumps(descriptor))
    with pytest.raises(ValueError): package(args)
    assert not args['output'].exists()


def test_signed_image_with_out_of_slot_vector_is_rejected(release):
    args, key = release
    descriptor = json.loads(args['release'].read_text())
    from tools.firmware.package_zigbee_ota import image
    blob = signed_image(key)
    parsed = image(blob)
    region = bytearray(blob[:parsed['authenticated_end']])
    struct.pack_into('<I', region, 516, 0x000b0201)
    digest = hashlib.sha256(region).digest()
    signature = key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    keyhash = hashlib.sha256(key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).digest()
    fields = struct.pack('<HH', 1, 32) + keyhash + struct.pack('<HH', 0x10, 32) + digest + struct.pack('<HH', 0x22, len(signature)) + signature
    invalid = bytes(region) + struct.pack('<HH', 0x6907, len(fields) + 4) + fields
    (args['release'].parent / 'main.signed.bin').write_bytes(invalid)
    descriptor['main']['sha256'] = sha(invalid)
    qpath = args['release'].parent / 'qualification.json'
    q = json.loads(qpath.read_text()); q['components']['main'] = sha(invalid)
    qpath.write_text(json.dumps(q)); descriptor['qualification']['sha256'] = sha(qpath.read_bytes())
    args['release'].write_text(json.dumps(descriptor))
    with pytest.raises(ValueError): package(args)
    assert not args['output'].exists()


@pytest.mark.parametrize('damage', ['keyhash', 'unknown-tlv', 'missing-keyhash', 'common-slot-overflow'])
def test_common_images_match_strict_firmware_key_tlv_and_capacity_contract(release, damage):
    args, key = release
    from tools.firmware.package_zigbee_ota import image
    blob = signed_image(key)
    parsed = image(blob); end = parsed['authenticated_end']
    if damage == 'keyhash':
        altered = bytearray(blob); altered[end + 8] ^= 1; invalid = bytes(altered)
    elif damage == 'unknown-tlv':
        altered = bytearray(blob + struct.pack('<HHB', 0xbeef, 1, 0))
        struct.pack_into('<H', altered, end + 2, len(altered) - end); invalid = bytes(altered)
    elif damage == 'missing-keyhash':
        altered = bytearray(blob[:end + 4] + blob[end + 40:])
        struct.pack_into('<H', altered, end + 2, len(altered) - end); invalid = bytes(altered)
    else:
        header = bytearray(blob[:512]); payload = blob[512:576] + bytes(0xa2200 - 512 - 64)
        struct.pack_into('<I', header, 12, len(payload))
        region = bytes(header) + payload + blob[576:end]
        digest = hashlib.sha256(region).digest()
        signature = key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        keyhash = hashlib.sha256(key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).digest()
        fields = struct.pack('<HH', 1, 32) + keyhash + struct.pack('<HH', 0x10, 32) + digest + struct.pack('<HH', 0x22, len(signature)) + signature
        invalid = region + struct.pack('<HH', 0x6907, len(fields) + 4) + fields
        assert 0xa2000 < len(invalid) < 0xa4000
    descriptor = json.loads(args['release'].read_text())
    (args['release'].parent / 'main.signed.bin').write_bytes(invalid)
    descriptor['main']['sha256'] = sha(invalid)
    qpath = args['release'].parent / 'qualification.json'
    q = json.loads(qpath.read_text()); q['components']['main'] = sha(invalid)
    qpath.write_text(json.dumps(q)); descriptor['qualification']['sha256'] = sha(qpath.read_bytes())
    args['release'].write_text(json.dumps(descriptor))
    with pytest.raises(ValueError): package(args)
    assert not args['output'].exists()
