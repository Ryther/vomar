"""Standalone Kotlin/JCA and authoritative C interop; no Gradle/key/device IO."""
import ctypes as c
import hashlib
import json
from pathlib import Path
import struct
import sys
import subprocess
import zlib
import io
import zipfile

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from tools.firmware.tests.local_inputs import local_input
from cryptography.hazmat.primitives.asymmetric import ec

ROOT = Path(__file__).resolve().parents[4]
ISLAND = ROOT / 'tools/android/first_install_contract'
CACHE = ROOT / 'work/android-gradle-cache/caches/modules-2/files-2.1'


def jar(group, name, version):
    matches = [p for p in (CACHE / group / name / version).glob('*/*.jar')
               if not p.name.endswith('-all.jar')]
    assert len(matches) == 1, (group, name, version, matches)
    return matches[0]


@pytest.fixture(scope='module')
def kotlin(tmp_path_factory):
    base = tmp_path_factory.mktemp('first_install_kotlin')
    compiler = [jar('org.jetbrains.kotlin', name, version) for name, version in [
        ('kotlin-compiler-embeddable', '2.4.21'), ('kotlin-build-tools-api', '2.4.21'), ('kotlin-stdlib', '2.4.21'),
        ('kotlin-script-runtime', '2.4.21'), ('kotlin-reflect', '1.6.10'),
        ('kotlin-daemon-embeddable', '2.4.21')]]
    compiler += [jar('org.jetbrains.kotlinx', 'kotlinx-coroutines-core-jvm', '1.8.0'),
                 jar('org.jetbrains', 'annotations', '23.0.0')]
    libraries = [jar('org.jetbrains.kotlin', 'kotlin-stdlib', '2.4.21')]
    libraries += [jar(group, name, version) for group, name, version in [
        ('org.jetbrains.kotlinx','kotlinx-coroutines-core-jvm','1.11.0'),
        ('org.jetbrains.kotlinx','kotlinx-serialization-core-jvm','1.12.0'),
        ('org.jetbrains.kotlinx','kotlinx-serialization-json-jvm','1.12.0'),
        ('org.apache.commons','commons-compress','1.28.0'),('commons-io','commons-io','2.20.0'),
        ('commons-codec','commons-codec','1.19.0'),('org.apache.commons','commons-lang3','3.18.0')]]
    output = base / 'installer.jar'
    args = ['java', '-cp', ':'.join(map(str, compiler)), 'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler',
            '-no-stdlib', '-no-reflect', '-jvm-target', '17', '-classpath', ':'.join(map(str, libraries)),
            '-Xplugin='+str(jar('org.jetbrains.kotlin','kotlin-serialization-compiler-plugin-embeddable','2.4.21')),
            '-d', str(output), *map(str, sorted((ISLAND / 'src').glob('*.kt'))),
            *map(str, sorted((ROOT/'apps/android-updater/core/src/main/kotlin/org/openvimar/updater/core').glob('*.kt'))),
            str(ROOT/'apps/android-updater/app/src/main/kotlin/org/openvimar/updater/DkBackupArchive.kt'),
            *map(str,sorted((ISLAND/'tests').glob('*.kt')))]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return ['java', '-Xmx256m', '-cp', ':'.join(map(str, [output, *libraries])), 'org.openvimar.installer.ProbeKt']


class Anchor(c.Structure):
    _fields_ = [('variant', c.c_uint32), ('uid', c.c_uint32 * 2),
                ('flash_sha256', c.c_uint8 * 32), ('uicr_sha256', c.c_uint8 * 32),
                ('table_sha256', c.c_uint8 * 32)]


class Live(c.Structure):
    _fields_ = [('part', c.c_uint32), ('variant', c.c_uint32), ('uid', c.c_uint32 * 2),
                ('flash_size', c.c_uint32), ('page_size', c.c_uint32),
                ('ram_size', c.c_uint32), ('uicr_size', c.c_uint32), ('uicr_sha256', c.c_uint8 * 32)]


@pytest.fixture(scope='module')
def authoritative_c(tmp_path_factory):
    out = tmp_path_factory.mktemp('first_install_c') / 'contract.so'
    subprocess.run(['cc', '-shared', '-fPIC', '-std=c11', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=undefined', '-fno-sanitize-recover=all',
        str(ROOT / 'firmware/loader_contract/loader_contract.c'), '-o', str(out)], check=True)
    lib = c.CDLL(str(out))
    lib.loader_anchor_encode.argtypes = [c.c_void_p, c.c_size_t, c.POINTER(Anchor)]
    lib.loader_anchor_decode.argtypes = [c.c_void_p, c.c_size_t, c.POINTER(Live), c.POINTER(Anchor)]
    return lib


def test_kotlin_anchor_is_byte_exact_c_encoder_and_c_decoder(kotlin, authoritative_c, tmp_path):
    values = [hashlib.sha256(name).digest() for name in [b'original flash', b'original UICR', b'table']]
    args = [str(tmp_path / 'anchor.bin'), '41414430', '11223344', '55667788', *[v.hex() for v in values]]
    subprocess.run([*kotlin, 'anchor', *args], check=True)
    actual = Path(args[0]).read_bytes()
    anchor = Anchor(0x41414430, (c.c_uint32 * 2)(0x11223344, 0x55667788),
                    *[(c.c_uint8 * 32).from_buffer_copy(v) for v in values])
    expected = c.create_string_buffer(4096)
    assert authoritative_c.loader_anchor_encode(expected, 4096, c.byref(anchor)) == 0
    assert actual == expected.raw
    assert struct.unpack_from('<I', actual, 248)[0] == zlib.crc32(actual[:248])
    live = Live(0x52840, 0x41414430, (c.c_uint32 * 2)(0x11223344, 0x55667788),
                0x100000, 4096, 0x40000, 4096, (c.c_uint8 * 32).from_buffer_copy(values[1]))
    decoded = Anchor()
    assert authoritative_c.loader_anchor_decode(actual, len(actual), c.byref(live), c.byref(decoded)) == 0
    assert bytes(decoded) == bytes(anchor)


@pytest.mark.parametrize('variant', ['0', 'ffffffff'])
def test_invalid_variant_never_produces_anchor(kotlin, tmp_path, variant):
    result = subprocess.run([*kotlin, 'anchor', str(tmp_path / 'bad'), variant, '11223344', '55667788',
                             *['11' * 32] * 3], capture_output=True)
    assert result.returncode != 0 and not (tmp_path / 'bad').exists()


def original_fixture():
    flash = bytearray((i * 37 + (i >> 12) * 13) & 255 for i in range(0x100000))
    struct.pack_into('<II', flash, 0, 0x20020000, 0x1001)
    flash[0xb0000:0xef000] = b'\xff' * 0x3f000
    ficr = bytearray(b'\xff' * 4096)
    for offset, value in [(0x10, 4096), (0x14, 256), (0x60, 0x11223344), (0x64, 0x55667788),
                          (0x100, 0x52840), (0x104, 0x41414430), (0x10c, 256), (0x110, 1024)]:
        struct.pack_into('<I', ficr, offset, value)
    regions = {'flash.bin': bytes(flash), 'ficr.bin': bytes(ficr), 'uicr.bin': b'\xff' * 4096}
    manifest = dict(schema=1, type='nrf52840-read-only-double-backup', target=dict(chip='nRF52840',
        part='0x00052840', uid=['0x11223344', '0x55667788'], identitySource='live FICR before/after both passes',
        commercialModelVerified=False, model='unknown nRF52840 device'), byteExactDoubleRead=True,
        startedAt='2026-10-23T12:00:00Z', verifiedAt='2026-10-23T12:02:00Z', snapshotAtomic=False,
        protocol=dict(id='jlink-raw-swd-ap0-read-v1', swdClockKhz=100, maxBlockBytes=512,
                      tarBoundaryBytes=1024, independentBlockSentinels=True),
        scope=dict(haltAttempted=False, resetAttempted=False, eraseAttempted=False, memoryWrite=False,
                   flashed=False, targetSupplyChanged=False, debugPortConfigured=True, restorationVerified=False),
        provenance=dict(appVersion='test', probeFirmware='synthetic probe', usbVendorId=0x1366,
            usbProductId=0x1060, interfaceId=4, inputEndpoint=0x85, outputEndpoint=3, targetMillivolts=3300),
        regions=[dict(file=name, start=f'0x{start:08x}', size=len(regions[name]),
                      sha256=hashlib.sha256(regions[name]).hexdigest(), verifiedCopies=2)
                 for name, start in [('flash.bin', 0), ('ficr.bin', 0x10000000), ('uicr.bin', 0x10001000)]])
    return regions, manifest


def archive(regions, manifest, *, raw_manifest=None, extra=None):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in regions.items(): z.writestr(name, data)
        z.writestr('manifest.json', raw_manifest if raw_manifest is not None else json.dumps(manifest))
        z.writestr('README.txt', 'Synthetic fixture. No hardware qualification.')
        if extra: z.writestr(*extra)
    return out.getvalue()


def test_verified_export_reopen_is_required_before_original_material_is_derived(kotlin, authoritative_c, tmp_path):
    regions, manifest = original_fixture(); source = tmp_path / 'backup.zip'; source.write_bytes(archive(regions, manifest))
    target = tmp_path / 'export.zip'; result = tmp_path / 'material'; result.mkdir()
    subprocess.run([*kotlin, 'backup', str(source), str(target), str(result), 'good'], check=True)
    assert target.read_bytes() == source.read_bytes()
    table = b''.join(hashlib.sha256(regions['flash.bin'][i:i+4096]).digest() for i in range(0, 0x100000, 4096))
    assert (result / 'table.bin').read_bytes() == table
    page = (result / 'anchor.bin').read_bytes(); decoded = Anchor()
    live = Live(0x52840, 0x41414430, (c.c_uint32 * 2)(0x11223344, 0x55667788),
                0x100000, 4096, 0x40000, 4096,
                (c.c_uint8 * 32).from_buffer_copy(hashlib.sha256(regions['uicr.bin']).digest()))
    assert authoritative_c.loader_anchor_decode(page, len(page), c.byref(live), c.byref(decoded)) == 0
    assert bytes(decoded.flash_sha256) == hashlib.sha256(regions['flash.bin']).digest()
    assert bytes(decoded.table_sha256) == hashlib.sha256(table).digest()


@pytest.mark.parametrize('mode', ['cancel', 'export-fails', 'reopen-fails', 'changed', 'same-regions-different-zip'])
def test_export_cancel_failure_reopen_or_nonidentical_zip_never_derives_install_material(kotlin, tmp_path, mode):
    regions, manifest = original_fixture(); source=tmp_path/'backup.zip';source.write_bytes(archive(regions,manifest))
    result=tmp_path/'material';result.mkdir()
    run=subprocess.run([*kotlin,'backup',str(source),str(tmp_path/'export.zip'),str(result),mode],capture_output=True)
    assert run.returncode != 0 and not list(result.iterdir())


@pytest.mark.parametrize('damage', ['uid', 'part', 'geometry', 'variant', 'vectors', 'region-sha',
    'scope', 'double-read', 'model-claim', 'duplicate-json', 'unknown-entry', 'scratch', 'zip-encrypted', 'zip-nonregular'])
def test_bad_original_bytes_metadata_and_unsupported_scratch_never_produce_anchor(kotlin,tmp_path,damage):
    regions,manifest=original_fixture();raw=None
    if damage in ['uid','part','geometry','variant']:
        data=bytearray(regions['ficr.bin']);struct.pack_into('<I',data,{'uid':0x60,'part':0x100,'geometry':0x10,'variant':0x104}[damage],0)
        regions['ficr.bin']=bytes(data);manifest['regions'][1]['sha256']=hashlib.sha256(data).hexdigest()
    if damage in ['vectors','scratch']:
        data=bytearray(regions['flash.bin']);data[0 if damage=='vectors' else 0xb0000]^=1
        regions['flash.bin']=bytes(data);manifest['regions'][0]['sha256']=hashlib.sha256(data).hexdigest()
    if damage=='region-sha':manifest['regions'][0]['sha256']='00'*32
    if damage=='scope':manifest['scope']['memoryWrite']=True
    if damage=='double-read':manifest['byteExactDoubleRead']=False
    if damage=='model-claim':manifest['target']['commercialModelVerified']=True
    if damage=='duplicate-json':raw=json.dumps(manifest).replace('"schema": 1','"schema": 1,"schema": 1')
    payload=bytearray(archive(regions,manifest,raw_manifest=raw,extra=('other',b'x') if damage=='unknown-entry' else None))
    if damage.startswith('zip-'):
        central=payload.index(b'PK\x01\x02')
        if damage=='zip-encrypted':struct.pack_into('<H',payload,central+8,1)
        else:struct.pack_into('<I',payload,central+38,0xa000<<16)
    source=tmp_path/'backup.zip';source.write_bytes(payload);result=tmp_path/'material';result.mkdir()
    run=subprocess.run([*kotlin,'backup',str(source),str(tmp_path/'export.zip'),str(result),'good'],capture_output=True)
    assert run.returncode!=0 and not list(result.iterdir()),damage


def canonical(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True)+'\n').encode()


def common_fixture(*,damage=None,candidate=False,watchdog_handoff=...):
    key=ec.generate_private_key(ec.SECP256R1())
    public=key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    def tlv(tag,value):return struct.pack('<HH',tag,len(value))+value
    def area(magic,value):return struct.pack('<HH',magic,len(value)+4)+value
    def component(name,role,base,version):
        payload=struct.pack('<II',0x20020000,base+521)+bytes(range(256))*4
        if damage=='vectors' and role==1:payload=struct.pack('<II',0x20020000,0xb0209)+payload[8:]
        actual_role=3 if damage=='role' and role==1 else role
        profile=1 if damage=='profile' and role==1 else 2
        protected=area(0x6908,tlv(0xa0,b'VIMAR30805'+bytes([profile]))+tlv(0xa1,bytes([actual_role])))
        header=struct.pack('<IIHHII',0x96f3b83d,0,512,len(protected),len(payload),0)+struct.pack('<BBHI',*version)+bytes(484)
        signed=header+payload+protected;digest=hashlib.sha256(signed).hexdigest()
        image=signed+area(0x6907,tlv(0x10,bytes.fromhex(digest))+tlv(1,hashlib.sha256(public).digest())+tlv(0x22,key.sign(signed,ec.ECDSA(hashes.SHA256()))))
        meta=dict(file=name,size=len(image),version='.'.join(map(str,version[:3])),wireVersion=list(version),
                  fileSha256=hashlib.sha256(image).hexdigest(),signedRegionSha256=digest,role={1:'MAIN',2:'RECOVERY'}[role])
        return image,meta
    main,main_meta=component('main.signed.bin',1,0xc000,(0,6,1,0))
    recovery,recovery_meta=component('recovery.signed.bin',2,0xb0000,(0,8,1,0))
    loader=bytearray(b'\xff'*0xc000);loader[:0x400]=bytes(range(256))*4;struct.pack_into('<II',loader,0,0x20020000,0x101)
    if damage=='anchor-not-erased':loader[0xb100]=0
    family=hashlib.sha256(b'VIMAR30805-LOADER-CODE44K-ANCHOR1\0'+loader[:0xb000]).hexdigest()
    record=dict(kind='common-code44k-anchor-v1',sha256=family)
    if damage=='typed-legacy':record['kind']='legacy-full48k-sha256'
    if damage=='unknown-kind':record['kind']='common-any-mask'
    if damage=='wrong-family':record['sha256']='00'*32
    def inner(meta):return {**{k:v for k,v in meta.items() if k not in ['wireVersion','fileSha256']},'sha256':meta['fileSha256']}
    descriptor=dict(schemaVersion=1,type='vimar30805-common-first-install',model='VIMAR30805',layoutVersion=2,identityProtocol=2,
        loaderContracts=[record],images=dict(loader=dict(file='loader.bin',size=len(loader),sha256=hashlib.sha256(loader).hexdigest()),main=inner(main_meta),recovery=inner(recovery_meta)))
    if watchdog_handoff is not ...:descriptor['watchdogHandoff']=watchdog_handoff
    if damage=='inner-main-mismatch':descriptor['images']['main']['sha256']='00'*32
    descriptor_bytes=canonical(descriptor);descriptor_sig=key.sign(descriptor_bytes,ec.ECDSA(hashes.SHA256()))
    if damage=='descriptor-signature':descriptor_sig=descriptor_sig[:-1]+bytes([descriptor_sig[-1]^1])
    outer=dict(schemaVersion=3,bundleId='',minAppVersion='0.5.0',model='VIMAR30805',layoutVersion=2,identityProtocol=2,
        loaderContracts=[record],legacyRecoverySignedHashes=[],targetRecoverySignedHash=recovery_meta['signedRegionSha256'],
        allowedSourceSignedHashes=['aa'*32],main=main_meta,recovery=recovery_meta,qualificationSha256='bb'*32,
        firstInstall=dict(file='first-install.json',size=len(descriptor_bytes),sha256=hashlib.sha256(descriptor_bytes).hexdigest(),
            signatureFile='first-install.sig',signatureSha256=hashlib.sha256(descriptor_sig).hexdigest()))
    qualification=None
    if candidate:
        checks=['zigbee_ota_completed','postboot_hash_verified','ble_recovery_verified','power_cut_recovery_verified',
            'split_stage_verified','loader_binding_verified','recovery_tail_preserved','mixed_profile_rejected',
            'protection_flash_radio_verified','stock_restore_verified','migration_verified','commonFirstFlashVerified','stockRestoreVerified']
        q=dict(schemaVersion=3,model='VIMAR30805',layoutVersion=2,loaderContracts=[record],
            components=dict(loader=hashlib.sha256(loader).hexdigest(),main=main_meta['fileSha256'],recovery=recovery_meta['fileSha256']),
            **dict.fromkeys(checks,False))
        if damage=='candidate-true':q['commonFirstFlashVerified']=True
        if damage=='candidate-int':q['commonFirstFlashVerified']=0
        if damage=='candidate-component':q['components']['main']='00'*32
        if damage=='candidate-extra':q['approvedForFlash']=False
        qualification=(json.dumps(q,indent=2)+'\n').encode()
        outer['purpose']='other' if damage=='candidate-purpose' else 'qualification-candidate'
        outer['qualificationSha256']='00'*32 if damage=='candidate-report-sha' else hashlib.sha256(qualification).hexdigest()
    if damage=='outer-main-mismatch':outer['main']=dict(main_meta,role='MIGRATION')
    if damage=='schema-downgrade':outer['schemaVersion']=2
    if damage=='unknown-outer-field':outer['allowedLoaderSha256']=[family]
    outer['bundleId']=hashlib.sha256(canonical({k:v for k,v in outer.items() if k!='bundleId'})).hexdigest()
    manifest=canonical(outer);signature=key.sign(manifest,ec.ECDSA(hashes.SHA256()))
    if damage=='manifest-signature':signature=signature[:-1]+bytes([signature[-1]^1])
    files={'manifest.json':manifest,'manifest.sig':signature,'first-install.json':descriptor_bytes,'first-install.sig':descriptor_sig,
           'loader.bin':bytes(loader),'main.signed.bin':main,'recovery.signed.bin':recovery}
    if qualification is not None and damage!='candidate-report-missing':files['qualification.json']=qualification
    if damage=='loader-damage':files['loader.bin']=bytes(loader[:100])+bytes([loader[100]^1])+bytes(loader[101:])
    if damage=='image-damage':files['main.signed.bin']=main[:700]+bytes([main[700]^1])+main[701:]
    if damage=='unexpected-entry':files['identity.json']=b'{}'
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as zip:
        for name,data in files.items():zip.writestr(name,data)
    return output.getvalue(),public,family,files


def test_one_common_zip_binds_both_public_signatures_exact_family_and_signed_components(kotlin,tmp_path):
    raw,key,family,_=common_fixture();source=tmp_path/'release.zip';source.write_bytes(raw);pub=tmp_path/'public.der';pub.write_bytes(key)
    output=tmp_path/'family.txt';subprocess.run([*kotlin,'release',str(source),str(pub),str(output)],check=True)
    assert output.read_text().strip()==family


@pytest.mark.parametrize('damage',['manifest-signature','descriptor-signature','loader-damage','image-damage',
    'anchor-not-erased','typed-legacy','unknown-kind','wrong-family','inner-main-mismatch','outer-main-mismatch',
    'schema-downgrade','unknown-outer-field','role','profile','vectors','unexpected-entry'])
def test_nonmatching_or_untrusted_common_zip_never_grants_install_authority(kotlin,tmp_path,damage):
    raw,key,_,_=common_fixture(damage=damage);source=tmp_path/'release.zip';source.write_bytes(raw);pub=tmp_path/'public.der';pub.write_bytes(key)
    output=tmp_path/'family.txt';run=subprocess.run([*kotlin,'release',str(source),str(pub),str(output)],capture_output=True)
    assert run.returncode!=0 and not output.exists(),damage


@pytest.fixture
def install_files(tmp_path):
    regions,manifest=original_fixture();backup=tmp_path/'backup.zip';backup.write_bytes(archive(regions,manifest))
    release,key,_,_=common_fixture();package=tmp_path/'release.zip';package.write_bytes(release);public=tmp_path/'public.der';public.write_bytes(key)
    return backup,package,public


def run_install(kotlin,paths,out,scenario):
    out.mkdir()
    run=subprocess.run([*kotlin,'install',*map(str,paths),scenario,str(out)],capture_output=True,text=True)
    assert run.returncode==0,run.stdout+run.stderr
    return (out/'result.txt').read_text().split(),(out/'trace.txt').read_text().splitlines()


def test_page_transactions_full_readback_commit_last_and_no_uicr_write(kotlin,install_files,tmp_path):
    result,trace=run_install(kotlin,install_files,tmp_path/'result','good')
    assert result[0]=='true' and result[3]=='true'
    commits=[i for i,line in enumerate(trace) if line=='program:45308:4']
    assert len(commits)==1
    assert all(not line.startswith(('erase:','program:')) for line in trace[commits[0]+1:])
    assert sum(line.startswith('erase:') for line in trace)==256
    assert 'journal:BODY_VERIFIED' in trace[:commits[0]] and 'journal:VERIFIED' in trace[commits[0]+1:]
    assert 256<=trace.count('uicr')<300 # Page boundaries, never one4KiB read per word/batch.


@pytest.mark.parametrize('scenario',['changed-original','changed-uicr','changed-uid','wrong-authorization',
    'cancel-page','generation-batch','uid-batch','lost-commit','corrupt-readback','existing-journal','journal-after-commit-intent','file-after-commit-intent','unreadable-journal'])
def test_identity_lease_cancellation_and_commit_uncertainty_stop_without_followon_writes(kotlin,install_files,tmp_path,scenario):
    result,_=run_install(kotlin,install_files,tmp_path/'result',scenario)
    assert result[0]=='false'


def test_file_journal_atomic_claim_durable_reopen_and_stale_intent_rejection(kotlin,tmp_path):
    subprocess.run([*kotlin,'journal',str(tmp_path/'journal')],check=True)
    files=list((tmp_path/'journal').glob('*.json'));assert len(files)==1
    record=json.loads(files[0].read_text());assert record['phase']=='PAGE_ERASE_INTENT'
    assert record['mutationMayHaveStarted'] is True and files[0].stat().st_size<8192


def test_complete_engine_uses_actual_durable_file_journal_without_memory_bytes(kotlin,install_files,tmp_path):
    out=tmp_path/'result';result,_=run_install(kotlin,install_files,out,'file-backed')
    assert result[0]=='true'
    files=list((out/'journal').iterdir());assert len(files)==1
    record=json.loads(files[0].read_text())
    assert record['phase']=='VERIFIED' and record['commitMayHaveBeenWritten'] is True
    assert files[0].stat().st_size<8192 and 'flash.bin' not in files[0].read_text()


def test_actual_kotlin_backup_producer_zip_reopens_and_derives_identical_original_table(kotlin,tmp_path):
    regions,_=original_fixture();raw=tmp_path/'raw';raw.mkdir()
    for name,data in regions.items():(raw/name).write_bytes(data)
    backup=tmp_path/'actual-producer.zip';subprocess.run([*kotlin,'produce-backup',str(raw),str(backup)],check=True)
    output=tmp_path/'material';output.mkdir()
    subprocess.run([*kotlin,'backup',str(backup),str(tmp_path/'export.zip'),str(output),'good'],check=True)
    assert (output/'table.bin').read_bytes()==b''.join(hashlib.sha256(regions['flash.bin'][i:i+4096]).digest() for i in range(0,0x100000,4096))


def test_every_mutation_and_journal_boundary_failure_stops_without_followon_target_write(kotlin,install_files,tmp_path):
    out=tmp_path/'sweep'
    subprocess.run([*kotlin,'sweep',*map(str,install_files),str(out)],check=True,capture_output=True)
    assert int((out/'count.txt').read_text())>=550


def test_independent_schema3_python_producer_zip_passes_kotlin_and_authoritative_c_family(kotlin,authoritative_c,tmp_path):
    fixture=ROOT/'tools/android/test-fixtures/common-v3-synthetic'
    output=tmp_path/'family.txt'
    subprocess.run([*kotlin,'release',str(fixture/'one-common.zip'),str(fixture/'public.der'),str(output),'9.0.0'],check=True)
    with zipfile.ZipFile(fixture/'one-common.zip') as z:loader=z.read('loader.bin')
    READ=c.CFUNCTYPE(c.c_int,c.c_void_p,c.c_uint32,c.c_void_p,c.c_size_t)
    BEGIN=c.CFUNCTYPE(c.c_int,c.c_void_p)
    UPDATE=c.CFUNCTYPE(c.c_int,c.c_void_p,c.c_void_p,c.c_size_t)
    FINISH=c.CFUNCTYPE(c.c_int,c.c_void_p,c.c_void_p)
    ABORT=c.CFUNCTYPE(None,c.c_void_p)
    class Reader(c.Structure):_fields_=[('ctx',c.c_void_p),('size',c.c_size_t),('read',READ)]
    class Hash(c.Structure):_fields_=[('ctx',c.c_void_p),('begin',BEGIN),('update',UPDATE),('finish',FINISH),('abort',ABORT)]
    state={};reads=[]
    @READ
    def read(ctx,offset,dest,size):
        assert offset+size<=0xb000;reads.append((offset,size));c.memmove(dest,loader[offset:offset+size],size);return 0
    @BEGIN
    def begin(ctx):state['hash']=hashlib.sha256();return 0
    @UPDATE
    def update(ctx,data,size):state['hash'].update(c.string_at(data,size));return 0
    @FINISH
    def finish(ctx,out):c.memmove(out,state['hash'].digest(),32);return 0
    @ABORT
    def abort(ctx):state.clear()
    reader=Reader(None,len(loader),read);hashes=Hash(None,begin,update,finish,abort);digest=c.create_string_buffer(32)
    authoritative_c.loader_contract_family_digest.argtypes=[c.POINTER(Reader),c.POINTER(Hash),c.c_void_p]
    assert authoritative_c.loader_contract_family_digest(c.byref(reader),c.byref(hashes),digest)==0
    assert output.read_text().strip()==digest.raw.hex()==hashlib.sha256(b'VIMAR30805-LOADER-CODE44K-ANCHOR1\0'+loader[:0xb000]).hexdigest()
    assert reads[0]==(0,256) and reads[-1]==(0xaf00,256)


def test_authenticated_components_and_descriptor_are_copied_for_android_core_consumer(kotlin,tmp_path):
    fixture=ROOT/'tools/android/test-fixtures/common-v3-synthetic'
    output=tmp_path/'authenticated'
    subprocess.run([*kotlin,'release',str(fixture/'one-common.zip'),str(fixture/'public.der'),str(output),'9.0.0','public-components'],check=True)
    with zipfile.ZipFile(fixture/'one-common.zip') as z:
        for name in ['loader.bin','main.signed.bin','recovery.signed.bin','first-install.json']:
            assert (output/name).read_bytes()==z.read(name)


@pytest.mark.parametrize('method',['debug-halt','reset-vector-catch'])
def test_quiescent_backup_contract_truthfully_records_halt_and_optional_reset(kotlin,tmp_path,method):
    regions,m=original_fixture()
    m['type']='nrf52840-quiescent-first-install-backup'
    m['protocol']['id']='jlink-raw-swd-ap0-halted-backup-v1'
    m['scope'].update(haltAttempted=True,memoryWrite=True,flashWrite=False,uicrWrite=False,resetAttempted=method=='reset-vector-catch')
    m['acquisition']=dict(cpuHalted=True,method=method,originalCpuControl=0)
    source=tmp_path/'quiescent.zip';source.write_bytes(archive(regions,m));output=tmp_path/'material';output.mkdir()
    subprocess.run([*kotlin,'backup',str(source),str(tmp_path/'export.zip'),str(output),'good'],check=True)
    verified=subprocess.run([sys.executable,str(ROOT/'tools/firmware/verify_android_backup.py'),'--backup',str(source)],capture_output=True,text=True)
    assert verified.returncode==0,verified.stderr
    result=json.loads(verified.stdout)
    assert result['producerReported']['scope']==m['scope']
    assert result['producerReported']['acquisition']==m['acquisition']
    assert result['restorationQualified'] is False


@pytest.mark.parametrize('method',['debug-halt','reset-vector-catch','mismatch','paused-watchdog'])
def test_actual_quiescent_kotlin_producer_requires_two_equal_complete_passes(kotlin,tmp_path,method):
    regions,_=original_fixture();raw=tmp_path/'raw';raw.mkdir()
    for name,data in regions.items():(raw/name).write_bytes(data)
    backup=tmp_path/'quiescent.zip'
    run=subprocess.run([*kotlin,'produce-quiescent',str(raw),str(backup),method],capture_output=True,text=True)
    if method=='mismatch':
        assert run.returncode!=0 and not backup.exists();return
    assert run.returncode==0,run.stderr
    with zipfile.ZipFile(backup) as z:
        m=json.loads(z.read('manifest.json'));assert m['acquisition']['method']==('debug-halt' if method=='paused-watchdog' else method)
        if method=='paused-watchdog':assert m['acquisition']['watchdog']==dict(runStatus=1,config=1,crv=0x50000,rren=1)
        for name,expected in regions.items():assert z.read(name)==expected
    subprocess.run([sys.executable,str(ROOT/'tools/firmware/verify_android_backup.py'),'--backup',str(backup)],check=True,capture_output=True)


def test_signed_candidate_is_separate_from_qualified_release_and_keeps_false_flags(kotlin,tmp_path):
    raw,key,family,_=common_fixture(candidate=True);source=tmp_path/'candidate.zip';source.write_bytes(raw);pub=tmp_path/'public.der';pub.write_bytes(key)
    output=tmp_path/'report.json'
    subprocess.run([*kotlin,'candidate-inspect',str(source),str(pub),str(output)],check=True)
    assert json.loads(output.read_text())['commonFirstFlashVerified'] is False
    normal=subprocess.run([*kotlin,'release',str(source),str(pub),str(tmp_path/'normal')],capture_output=True)
    assert normal.returncode!=0 and not (tmp_path/'normal').exists()


@pytest.mark.parametrize('damage',['candidate-true','candidate-int','candidate-component','candidate-extra','candidate-purpose','candidate-report-sha','candidate-report-missing'])
def test_resigned_candidate_cannot_inflate_or_change_pending_qualification_authority(kotlin,tmp_path,damage):
    raw,key,_,_=common_fixture(candidate=True,damage=damage);source=tmp_path/'candidate.zip';source.write_bytes(raw);pub=tmp_path/'public.der';pub.write_bytes(key)
    run=subprocess.run([*kotlin,'candidate-inspect',str(source),str(pub),str(tmp_path/'result')],capture_output=True)
    assert run.returncode!=0 and not (tmp_path/'result').exists()


def test_fresh_single_bench_permit_is_one_shot_uid_request_and_generation_bound(kotlin,tmp_path):
    raw,key,_,_=common_fixture(candidate=True);source=tmp_path/'candidate.zip';source.write_bytes(raw);pub=tmp_path/'public.der';pub.write_bytes(key)
    regions,m=original_fixture();backup=tmp_path/'backup.zip';backup.write_bytes(archive(regions,m))
    subprocess.run([*kotlin,'candidate-permit',str(source),str(pub),str(backup)],check=True)


@pytest.mark.parametrize('scenario',['bench-good','bench-wrong-generation'])
def test_candidate_plan_retains_live_lease_generation_through_engine_admission(kotlin,tmp_path,scenario):
    raw,key,_,_=common_fixture(candidate=True);source=tmp_path/'candidate.zip';source.write_bytes(raw);pub=tmp_path/'public.der';pub.write_bytes(key)
    regions,m=original_fixture();backup=tmp_path/'backup.zip';backup.write_bytes(archive(regions,m))
    run_install(kotlin,(backup,source,pub),tmp_path/'run',scenario)


def test_independent_python_full_candidate_zip_passes_separate_kotlin_inspection_only(kotlin,tmp_path):
    fixture=ROOT/'tools/android/test-fixtures/common-v3-candidate'
    subprocess.run([*kotlin,'candidate-inspect',str(fixture/'qualification-candidate.zip'),str(fixture/'public.der'),str(tmp_path/'report.json')],check=True)
    assert json.loads((tmp_path/'report.json').read_text())['stockRestoreVerified'] is False
    default=subprocess.run([*kotlin,'release',str(fixture/'qualification-candidate.zip'),str(fixture/'public.der'),str(tmp_path/'default')],capture_output=True)
    assert default.returncode!=0


@pytest.mark.parametrize('candidate',[False,True])
def test_signed_watchdog_handoff_authority_is_exact_release_uid_family_and_generation_bound(kotlin,tmp_path,candidate):
    raw,key,_,_=common_fixture(candidate=candidate,watchdog_handoff='paused-reset-before-main-v1')
    source=tmp_path/'release.zip';source.write_bytes(raw);pub=tmp_path/'public.der';pub.write_bytes(key)
    subprocess.run([*kotlin,'watchdog-authority',str(source),str(pub),'candidate' if candidate else 'qualified'],check=True)


@pytest.mark.parametrize('policy',[None,'reset-before-main-v1','paused-reset-before-main-v2',True,1])
def test_signed_unknown_watchdog_handoff_is_rejected(kotlin,tmp_path,policy):
    raw,key,_,_=common_fixture(watchdog_handoff=policy);source=tmp_path/'release.zip';source.write_bytes(raw);pub=tmp_path/'public.der';pub.write_bytes(key)
    result=subprocess.run([*kotlin,'release',str(source),str(pub),str(tmp_path/'invalid')],capture_output=True)
    assert result.returncode!=0 and not (tmp_path/'invalid').exists()


def test_independent_python_watchdog_descriptor_fixtures_preserve_exact_signed_capability(kotlin,tmp_path):
    fixtures=ROOT/'experiments/inherited-watchdog-contract-20261023'
    local_input(fixtures/'synthetic-public.der')
    for purpose in ['qualified','candidate']:local_input(fixtures/f'synthetic-{purpose}.zip')
    for purpose in ['qualified','candidate']:
        subprocess.run([*kotlin,'watchdog-authority',str(fixtures/f'synthetic-{purpose}.zip'),str(fixtures/'synthetic-public.der'),purpose],check=True)


def test_real_signed_watchdog_candidate_has_capability_but_normal_release_still_rejects(kotlin,tmp_path):
    fixture=local_input(ROOT/'experiments/common-candidate-0.6.2-20261023-watchdog-v1/vimar-30805-0.6.2-qualification-candidate.zip')
    assert hashlib.sha256(fixture.read_bytes()).hexdigest()=='665dba4b5ad4a852f384522e7133c2488b04e28b8ccd946bb012a7fb0eb3f40b'
    key=serialization.load_pem_public_key((ROOT/'firmware/keys/dev-public.pem').read_bytes())
    public=tmp_path/'public.der';public.write_bytes(key.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo))
    subprocess.run([*kotlin,'watchdog-authority',str(fixture),str(public),'candidate'],check=True)
    normal=subprocess.run([*kotlin,'watchdog-authority',str(fixture),str(public),'qualified'],capture_output=True)
    assert normal.returncode!=0


@pytest.mark.parametrize('changed',[{'runStatus':True},{'runStatus':2},{'config':9},{'rren':0},{'crv':60*32768},{'rren':256},{'unknown':1},{'crv':None}])
def test_quiescent_watchdog_observation_rejects_malformed_or_unsafe_active_shape(kotlin,tmp_path,changed):
    regions,m=original_fixture();m['type']='nrf52840-quiescent-first-install-backup';m['protocol']['id']='jlink-raw-swd-ap0-halted-backup-v1'
    m['scope'].update(haltAttempted=True,memoryWrite=True,flashWrite=False,uicrWrite=False)
    w=dict(runStatus=1,config=1,crv=0x50000,rren=1);w.update(changed)
    m['acquisition']=dict(cpuHalted=True,method='debug-halt',originalCpuControl=0,watchdog=w)
    source=tmp_path/'invalid.zip';source.write_bytes(archive(regions,m));output=tmp_path/'out';output.mkdir()
    for command in [[*kotlin,'backup',str(source),str(tmp_path/'export.zip'),str(output),'good'],
                    [sys.executable,str(ROOT/'tools/firmware/verify_android_backup.py'),'--backup',str(source)]]:
        assert subprocess.run(command,capture_output=True).returncode!=0


def test_every_app_owned_directory_entry_is_durable_before_publication(kotlin,tmp_path):
    subprocess.run([*kotlin,'durable-directories',str(tmp_path)],check=True)


@pytest.mark.parametrize('scenario',['good','wrong-uid','wrong-uicr','wrong-ficr','wrong-generation','cancel','readback'])
def test_original_restore_exact_private_backup_is_bound_to_live_device_and_durable_page_intents(kotlin,tmp_path,scenario):
    regions,manifest=original_fixture();source=tmp_path/'original.zip';source.write_bytes(archive(regions,manifest))
    subprocess.run([*kotlin,'original-restore',str(source),str(tmp_path),scenario],check=True)


@pytest.mark.parametrize('candidate',[False,True])
@pytest.mark.parametrize('signatures',['present','missing','invalid'])
def test_local_packages_accept_outer_unsigned_without_qualifying_online_release(kotlin,tmp_path,candidate,signatures):
    raw,key,_,_=common_fixture(candidate=candidate)
    if signatures!='present':
        with zipfile.ZipFile(io.BytesIO(raw)) as z: entries={name:z.read(name) for name in z.namelist()}
        for name in ['manifest.sig','first-install.sig']:
            if signatures=='missing': entries.pop(name)
            else: entries[name]=b'bad signature'
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            for name,data in entries.items():z.writestr(name,data)
        raw=out.getvalue()
    source=tmp_path/'local.zip';source.write_bytes(raw);pub=tmp_path/'public.der';pub.write_bytes(key)
    subprocess.run([*kotlin,'local-inspect',str(source),str(pub)],check=True)
    if signatures!='present':
        result=subprocess.run([*kotlin,'release',str(source),str(pub),str(tmp_path)],capture_output=True)
        assert result.returncode!=0,'Unsigned local artifact must not gain qualified release authority'



def test_local_unsigned_descriptor_cannot_invent_active_watchdog_authority(kotlin,tmp_path):
    raw,key,_,_=common_fixture(candidate=True,watchdog_handoff='paused-reset-before-main-v1')
    with zipfile.ZipFile(io.BytesIO(raw)) as z: entries={name:z.read(name) for name in z.namelist() if name!='first-install.sig'}
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in entries.items():z.writestr(name,data)
    source=tmp_path/'local.zip';source.write_bytes(out.getvalue());pub=tmp_path/'public.der';pub.write_bytes(key)
    subprocess.run([*kotlin,'local-inspect',str(source),str(pub),'no-handoff'],check=True)
