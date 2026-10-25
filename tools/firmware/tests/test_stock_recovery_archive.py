"""Synthetic private recovery archives; temporary signing keys, no hardware IO."""
import hashlib
import io
import json
import struct
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from intelhex import IntelHex


def sha(data):
    return hashlib.sha256(data).hexdigest()


def archive(path, files):
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)


def read_archive(path):
    with zipfile.ZipFile(path) as z:
        return {name: z.read(name) for name in z.namelist()}


def signed(key, payload, base, *, flags=0, load=0):
    payload = struct.pack('<II', 0x20010000, base + 521) + payload
    header = bytearray(512)
    struct.pack_into('<II', header, 0, 0x96f3b83d, load)
    struct.pack_into('<HHII', header, 8, 512, 0, len(payload), flags)
    struct.pack_into('<BBHI', header, 20, 0, 6, 4, 0)
    region = bytes(header) + payload
    digest = hashlib.sha256(region).digest()
    keyhash = hashlib.sha256(key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).digest()
    signature = key.sign(region, ec.ECDSA(hashes.SHA256()))
    fields = struct.pack('<HH', 1, 32) + keyhash + struct.pack('<HH', 0x10, 32) + digest + struct.pack('<HH', 0x22, len(signature)) + signature
    return region + struct.pack('<HH', 0x6907, len(fields) + 4) + fields


@pytest.fixture
def sources(tmp_path):
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    public_path = tmp_path / 'trusted-public.pem'; public_path.write_bytes(public)
    flash = b'\x5a' * 0xb0000 + b'\xff' * 0x3f000 + b'\xa5' * 0x11000
    uicr = b'\xff' * 4096
    ficr = bytearray(b'\xff' * 4096)
    struct.pack_into('<II', ficr, 0x60, 0x11223344, 0x55667788)
    struct.pack_into('<II', ficr, 0x100, 0x52840, 0xafa7b332)
    dumps = {'stock-flash.bin': flash, 'stock-uicr.bin': uicr, 'stock-ficr.bin': bytes(ficr)}
    evidence = {name: dict(size=len(data), sha256=sha(data), double_read_identical=True)
                for name, data in [('flash', flash), ('uicr', uicr), ('ficr', bytes(ficr))]}
    backup = tmp_path / 'stock-backup.zip'
    archive(backup, {**dumps, 'backup-result.json': json.dumps(evidence).encode()})
    pagehashes = b''.join(hashlib.sha256(flash[offset:offset + 4096]).digest() for offset in range(0, len(flash), 4096))
    restorer = signed(key, b'restorer' + struct.pack('<II', 0x11223344, 0x55667788) + hashlib.sha256(uicr).digest() + pagehashes, 0xb0000)
    bootstrap = signed(key, b'bridge' + struct.pack('<II', 0x11223344, 0x55667788) + restorer, 0xc000)
    recovery = signed(key, b'recovery' + bytes(32), 0xb0000)
    loader = bytearray(b'\xff' * 0xc000)
    loader[1024:1056] = hashlib.sha256(restorer).digest()
    struct.pack_into('<I', loader, 1080, len(restorer))
    def hex_bytes(blob, base):
        h = IntelHex(); h.frombytes(blob, offset=base); text = io.StringIO(); h.write_hex_file(text)
        return text.getvalue().encode()
    files = {**dumps, 'README.txt': b'Original private restoration instructions.\n',
             'restorer.signed.bin': restorer, 'restore-bootstrap.signed.bin': bootstrap,
             'loader.hex': hex_bytes(loader, 0), 'recovery.signed.hex': hex_bytes(recovery, 0xb0000),
             'signing-public.pem': public, 'enter_restore_via_ble.py': b'# original entry tool\n',
             'restore_via_ble.py': b'# original restoration tool\n', 'research_console.py': b'# original pairing helper\n',
             'logs/.keep': b''}
    manifest = dict(deviceid=['11223344', '55667788'], flash_sha256=sha(flash), uicr_sha256=sha(uicr),
                    status='Build verified; physical BLE stock restoration not yet qualified on this unit',
                    artifacts={name: dict(size=len(files[name]), sha256=sha(files[name])) for name in
                               ['restorer.signed.bin', 'restore-bootstrap.signed.bin', 'loader.hex', 'recovery.signed.hex', 'signing-public.pem']},
                    package_files={name: sha(data) for name, data in files.items() if name != 'logs/.keep'})
    files['artifact-manifest.json'] = json.dumps(manifest).encode()
    restore = tmp_path / 'ble-stock-restore.zip'; archive(restore, files)
    return dict(backup=backup, restore=restore, public_key=public_path, output=tmp_path / 'stock-recovery.zip'), key


def package(args):
    from tools.firmware.package_stock_recovery import create_stock_recovery_archive
    return create_stock_recovery_archive(**args)


def test_one_private_archive_deduplicates_backup_and_preserves_original_ble_tools(sources):
    args, _ = sources
    original = {role: args[role].read_bytes() for role in ('backup', 'restore')}
    result = package(args)
    files = read_archive(args['output'])
    m = json.loads(files['manifest.json'])
    assert m['kind'] == 'private-stock-recovery'
    assert m['device']['uid'] == ['11223344', '55667788']
    assert m['device']['uidSource']['offset'] == 0x60
    assert m['scope']['flash']['size'] == 0x100000
    assert m['scope']['ficr']['restore'] == 'factory-read-only; identity evidence; never program'
    assert m['verification']['signedRestorerPageTableMatchesAll256Pages'] is True
    assert m['physicalRestorationQualifiedByThisExport'] is False
    assert not any(name.endswith('.zip') for name in files)
    restore = read_archive(args['restore'])
    for name, data in restore.items():
        assert files[name] == data
    assert args['output'].stat().st_mode & 0o777 == 0o600
    assert result['sha256'] == sha(args['output'].read_bytes())
    assert original == {role: args[role].read_bytes() for role in ('backup', 'restore')}


@pytest.mark.parametrize('damage', ['uid', 'ficr-copy', 'backup-hash', 'backup-not-double', 'image-signature',
                                   'signed-page-table', 'signed-uicr-binding', 'signed-uid-binding', 'embedded-restorer',
                                   'loader-gate', 'package-hash', 'wrong-public-key', 'unexpected-secret', 'traversal'])
def test_refuses_mismatched_or_unbound_material_before_output(sources, damage):
    args, key = sources
    backup = read_archive(args['backup']); restore = read_archive(args['restore'])
    m = json.loads(restore['artifact-manifest.json'])
    if damage == 'uid': m['deviceid'][0] = '00000000'
    if damage == 'ficr-copy': restore['stock-ficr.bin'] = bytes(4096)
    if damage in ('backup-hash', 'backup-not-double'):
        evidence = json.loads(backup['backup-result.json'])
        evidence['flash']['sha256' if damage == 'backup-hash' else 'double_read_identical'] = '0' * 64 if damage == 'backup-hash' else False
        backup['backup-result.json'] = json.dumps(evidence).encode()
    if damage == 'image-signature': restore['restorer.signed.bin'] = restore['restorer.signed.bin'][:-1] + bytes([restore['restorer.signed.bin'][-1] ^ 1])
    if damage in ('signed-page-table', 'signed-uicr-binding', 'signed-uid-binding'):
        uid = bytes.fromhex('4433221188776655') if damage != 'signed-uid-binding' else bytes(8)
        uicrhash = hashlib.sha256(backup['stock-uicr.bin']).digest() if damage != 'signed-uicr-binding' else bytes(32)
        table = b''.join(hashlib.sha256(backup['stock-flash.bin'][i:i + 4096]).digest() for i in range(0, 0x100000, 4096)) if damage != 'signed-page-table' else bytes(8192)
        restore['restorer.signed.bin'] = signed(key, b'restorer' + uid + uicrhash + table, 0xb0000)
    if damage == 'embedded-restorer': restore['restore-bootstrap.signed.bin'] = signed(key, b'wrong bridge' + bytes.fromhex('4433221188776655'), 0xc000)
    if damage == 'loader-gate': restore['loader.hex'] = b':0400000001020304F2\n:00000001FF\n'
    if damage == 'wrong-public-key':
        other = ec.generate_private_key(ec.SECP256R1())
        args['public_key'].write_bytes(other.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    if damage == 'unexpected-secret': restore['private-key.pem'] = b'never copy extra secret files'
    if damage == 'traversal': restore['../outside'] = b'bad'
    # Recompute unsigned manifest metadata: signed binary bindings must still reject.
    if damage != 'package-hash':
        for name in m['package_files']:
            m['package_files'][name] = sha(restore[name])
        for name in m['artifacts']:
            m['artifacts'][name] = dict(size=len(restore[name]), sha256=sha(restore[name]))
    else: m['package_files']['stock-flash.bin'] = '0' * 64
    restore['artifact-manifest.json'] = json.dumps(m).encode()
    archive(args['backup'], backup); archive(args['restore'], restore)
    with pytest.raises(ValueError): package(args)
    assert not args['output'].exists()


def test_never_overwrites_or_writes_immutable_inputs(sources):
    args, _ = sources
    args['output'].write_bytes(b'keep')
    with pytest.raises(ValueError): package(args)
    assert args['output'].read_bytes() == b'keep'
    args['output'] = Path(__file__).resolve().parents[3] / 'inputs/forbidden-stock-recovery.zip'
    with pytest.raises(ValueError): package(args)
    assert not args['output'].exists()


def test_standalone_verifier_runs_without_the_repository_and_detects_modified_dump(sources, tmp_path):
    import subprocess
    import sys
    args, _ = sources
    package(args)
    files = read_archive(args['output'])
    isolated = tmp_path / 'extracted'; isolated.mkdir()
    script = isolated / 'verify-stock-recovery.py'; script.write_bytes(files['verify-stock-recovery.py'])
    key = isolated / 'signing-public.pem'; key.write_bytes(files['signing-public.pem'])
    command = [sys.executable, str(script), '--verify', str(args['output']), '--public-key', str(key)]
    verified = subprocess.run(command, cwd=isolated, text=True, capture_output=True)
    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)['signaturesAndBackupBindingsVerified'] is True
    files['stock-flash.bin'] = bytes(0x100000)
    damaged = isolated / 'damaged.zip'; archive(damaged, files)
    rejected = subprocess.run([*command[:3], str(damaged), *command[4:]], cwd=isolated, text=True, capture_output=True)
    assert rejected.returncode != 0


def test_rejects_symlink_and_duplicate_input_entries(sources):
    args, _ = sources
    files = read_archive(args['restore'])
    for damage in ('symlink', 'duplicate'):
        with zipfile.ZipFile(args['restore'], 'w') as zipped:
            for name, data in files.items():
                info = zipfile.ZipInfo(name)
                info.external_attr = (0o120777 if damage == 'symlink' and name == 'README.txt' else 0o100600) << 16
                zipped.writestr(info, data)
            if damage == 'duplicate':
                with pytest.warns(UserWarning, match='Duplicate'):
                    zipped.writestr('README.txt', files['README.txt'])
        with pytest.raises(ValueError): package(args)
        assert not args['output'].exists()


def test_modified_consolidated_scope_cannot_claim_factory_programming_or_qualification(sources):
    args, _ = sources
    package(args)
    files = read_archive(args['output'])
    m = json.loads(files['manifest.json'])
    m['scope']['ficr']['restore'] = 'program factory identity'
    m['physicalRestorationQualifiedByThisExport'] = True
    files['manifest.json'] = json.dumps(m).encode()
    damaged = args['output'].with_name('bad-scope.zip'); archive(damaged, files)
    from tools.firmware.package_stock_recovery import verify_stock_recovery_archive
    with pytest.raises(ValueError): verify_stock_recovery_archive(damaged, args['public_key'])


@pytest.mark.parametrize('flags,load,accepted', [(0x100, 0xb0000, True), (0x100, 0xc000, False), (0x104, 0xb0000, False)])
def test_legacy_fixed_address_recovery_accepts_only_its_exact_slot(sources, flags, load, accepted):
    args, key = sources
    restore = read_archive(args['restore'])
    blob = signed(key, b'fixed address legacy recovery' + bytes(32), 0xb0000, flags=flags, load=load)
    h = IntelHex(); h.frombytes(blob, offset=0xb0000); text = io.StringIO(); h.write_hex_file(text)
    restore['recovery.signed.hex'] = text.getvalue().encode()
    m = json.loads(restore['artifact-manifest.json'])
    m['package_files']['recovery.signed.hex'] = sha(restore['recovery.signed.hex'])
    m['artifacts']['recovery.signed.hex'] = dict(size=len(restore['recovery.signed.hex']), sha256=sha(restore['recovery.signed.hex']))
    restore['artifact-manifest.json'] = json.dumps(m).encode(); archive(args['restore'], restore)
    if accepted:
        package(args)
        assert args['output'].exists()
    else:
        with pytest.raises(ValueError): package(args)
        assert not args['output'].exists()


LEGACY_NAMES = ('CMakeLists.txt',
 'README.md',
 'application-ota-result.json',
 'application.signed.bin',
 'application.signed.hex',
 'artifact-manifest.json',
 'bootstrap/CMakeLists.txt',
 'bootstrap/main.c',
 'bootstrap/prj.conf',
 'bootstrap/restorer_blob.h',
 'build_candidate.py',
 'effective-uicr-checks.json',
 'enter_restore_via_ble.py',
 'gate.conf',
 'initial-install.hex',
 'loader.hex',
 'logs/application-ota-events.jsonl',
 'logs/bootstrap-build.log',
 'logs/bootstrap-ota-events.jsonl',
 'logs/loader-build.log',
 'logs/pipeline.log',
 'logs/research-main-build.log',
 'logs/restore-events.jsonl',
 'logs/restorer-build.log',
 'logs/verify-build-vimar-ble-no-uicr.log',
 'logs/verify-build-vimar-stock-restore-bootstrap-no-uicr.log',
 'logs/verify-build-vimar-stock-restorer-no-uicr.log',
 'main.c',
 'portable-inventory.json',
 'prepare_clients.py',
 'prepare_sources.py',
 'prj.conf',
 'probe_manifest.h',
 'recovery.signed.hex',
 'reinstallation-result.json',
 'research_console.py',
 'restore-bootstrap.signed.bin',
 'restore_flasher.c',
 'restore_flasher.h',
 'restore_via_ble.py',
 'restorer.overlay',
 'restorer.signed.bin',
 'signing-public.pem',
 'source-manifest.json',
 'stock-ficr.bin',
 'stock-flash.bin',
 'stock-restore-result.json',
 'stock-uicr.bin',
 'test_application_ota.py',
 'uicr-restoration-result.json',
 'update-images.hex')


def legacy_guard(form, *, mutation=None):
    """Independent synthetic encoding of the two audited compiler guard blocks."""
    # Synthetic variant + the fixed audited Thumb adds yields synthetic UID0 0x11223344.
    constant, loaded = (1,0) if form=='restorer' else (2,1)
    code=bytearray(bytes.fromhex('4ff08053')+bytes(2)+bytes.fromhex('d3f800119142'))
    if form=='restorer':code+=bytes.fromhex('8fb0')+bytes(2)
    part_branch=len(code);code+=bytes(2)
    at=len(code)
    code+=bytes.fromhex('d3f80401' if form=='restorer' else 'd3f80411')+bytes(2)
    code+=struct.pack('<H',0x4280|(constant<<3)|loaded)+bytes(2)
    code+=bytes.fromhex('01f1c241' if form=='restorer' else '02f1c242')
    code+=struct.pack('<H',0x6e18|loaded)
    code+=bytes.fromhex('01f5f501' if form=='restorer' else '02f5f502')
    code+=struct.pack('<HH',0x3012|(constant<<8),0x4280|(constant<<3)|loaded)+bytes(2)
    code+=struct.pack('<H',0x6e58|constant)+bytes(2)+struct.pack('<H',0x4298|constant)+bytes(2)
    if form=='restorer':
        code+=bytes.fromhex('01207047')
        while len(code)<64:code+=bytes.fromhex('00bf')
        refusal=len(code)
        code+=bytes.fromhex('00231370')+bytes(4)+bytes.fromhex('012100f000f800200fb05df804fb')
        failure_loads=[(refusal+4,2),(refusal+6,0)]
        success=None
    else:
        refusal=len(code)
        code+=bytes(4)+bytes.fromhex('012100f000f8002070bd')
        success=len(code);code+=bytes.fromhex('01207047')
        failure_loads=[(refusal,2),(refusal+2,0)]
    while len(code)%4:code+=b'\0'
    literals={}
    for name,value in [('part',0x52840),('variant',0xafa7b332),('uid1',0x55667788),('ptr',0x20001000),('log',0x00010000)]:
        literals[name]=len(code);code+=struct.pack('<I',value)
    def ldr(pos,register,name):
        distance=literals[name]-((pos+4)&~3)
        assert distance>=0 and distance%4==0 and distance//4<=255
        struct.pack_into('<H',code,pos,0x4800|(register<<8)|(distance//4))
    def branch(pos,condition,target):
        delta=target-(pos+4);assert delta%2==0 and -256<=delta<=254
        struct.pack_into('<H',code,pos,0xd000|(condition<<8)|((delta//2)&255))
    ldr(4,2,'part')
    if form=='restorer':ldr(14,2,'ptr')
    branch(part_branch,1,refusal)
    ldr(at+4,constant,'variant');branch(at+8,1,refusal);branch(at+24,1,refusal)
    ldr(at+28,3,'uid1')
    branch(at+32,1 if form=='restorer' else 0,refusal if form=='restorer' else success)
    for pos,register in failure_loads:ldr(pos,register,'log')
    if mutation=='cmp-nop':struct.pack_into('<H',code,at+22,0xbf00)
    if mutation=='refusal-branch':branch(at+24,1,refusal+2)
    if mutation=='variant':struct.pack_into('<I',code,literals['variant'],0xafa7b333)
    if mutation=='literal-out-of-bounds':struct.pack_into('<H',code,at+28,0x4bff)
    if mutation=='truncated-refusal':return bytes(code[:refusal+8])
    assert struct.pack('<I',0x11223344) not in code
    return bytes(code)


@pytest.fixture
def legacy_sources(sources):
    args, key = sources
    current = read_archive(args['restore'])
    ficr=bytearray(current['stock-ficr.bin']);struct.pack_into('<II',ficr,0x60,0x11223344,0x55667788);current['stock-ficr.bin']=bytes(ficr)
    table=b''.join(hashlib.sha256(current['stock-flash.bin'][i:i+4096]).digest() for i in range(0,0x100000,4096))
    current['restorer.signed.bin']=signed(key,legacy_guard('restorer')+hashlib.sha256(current['stock-uicr.bin']).digest()+table,0xb0000)
    current['restore-bootstrap.signed.bin']=signed(key,legacy_guard('bootstrap')+current['restorer.signed.bin'],0xc000)
    h=IntelHex(io.StringIO(current['loader.hex'].decode()));h.puts(1024,hashlib.sha256(current['restorer.signed.bin']).digest());h.puts(1080,struct.pack('<I',len(current['restorer.signed.bin'])));text=io.StringIO();h.write_hex_file(text);current['loader.hex']=text.getvalue().encode()
    portable = {name: current.get(name, b'# synthetic legacy source\n') for name in LEGACY_NAMES}
    portable['README.md'] = current['README.txt']
    app = signed(key, b'legacy application fixture' + bytes(32), 0xc000)
    portable['application.signed.bin'] = app
    def as_hex(blob, base):
        h = IntelHex(); h.frombytes(blob, offset=base); text = io.StringIO(); h.write_hex_file(text)
        return text.getvalue().encode()
    portable['application.signed.hex'] = as_hex(app, 0xc000)
    portable['initial-install.hex'] = portable['loader.hex']
    portable['update-images.hex'] = portable['loader.hex']
    physical = dict(whole_flash_exact=True, uicr_exact=True, ficr_exact=True,
                    flash_sha256=sha(current['stock-flash.bin']), runtime_uicr_original=True,
                    original_app_functional_test='not performed')
    portable['stock-restore-result.json'] = json.dumps(physical).encode()
    portable['uicr-restoration-result.json'] = json.dumps(dict(uicr_sha256=sha(current['stock-uicr.bin']), authorized=True)).encode()
    portable['application-ota-result.json'] = json.dumps(dict(ble_upload_completed=True)).encode()
    portable['reinstallation-result.json'] = json.dumps(dict(full_flash_matches_expected=True)).encode()
    portable['effective-uicr-checks.json'] = json.dumps({name: dict(disable_flash_patch='n',startup_uicr_macros=[],disable_flash_patch_symbol=False) for name in ['bootstrap','main','mcuboot','recovery','restorer']}).encode()
    m = json.loads(current['artifact-manifest.json']); m.pop('package_files')
    m['status'] = 'PHYSICALLY VALIDATED ON EXACT VIMAR; source report, not a test by this export'
    m['variant'] = 'afa7b332'
    m['deviceid']=['11223344','55667788']
    m['artifacts'] = {name: dict(size=len(portable[name]),sha256=sha(portable[name])) for name in
        ['initial-install.hex','update-images.hex','loader.hex','application.signed.bin','application.signed.hex',
         'recovery.signed.hex','restorer.signed.bin','restore-bootstrap.signed.bin','signing-public.pem']}
    m['physical_evidence'] = {name: sha(portable[name]) for name in
        ['application-ota-result.json','stock-restore-result.json','reinstallation-result.json','uicr-restoration-result.json']}
    portable['artifact-manifest.json'] = json.dumps(m).encode()
    portable['source-manifest.json'] = json.dumps({name:m[name] for name in ['deviceid','variant','flash_sha256','uicr_sha256']}).encode()
    portable['portable-inventory.json'] = json.dumps({name:dict(bytes=len(blob),sha256=sha(blob))
        for name,blob in portable.items() if name!='portable-inventory.json'}).encode()
    backup = {}
    for kind in ('flash','uicr','ficr'):
        for suffix in ('a','b'):
            backup[f'legacy-capture/{kind}-{suffix}.bin'] = current[f'stock-{kind}.bin']
    archive(args['backup'],backup)
    archive(args['restore'],{'legacy-portable/'+name:blob for name,blob in portable.items()})
    args.update(backup_format='legacy-double-read', restore_format='legacy-portable')
    return args, key


def test_legacy_pair_is_checked_and_preserved_without_requiring_identity_descriptor(legacy_sources):
    args, _ = legacy_sources
    package(args)
    files = read_archive(args['output']); m = json.loads(files['manifest.json'])
    assert m['sourceFormats'] == {'backup':'legacy-double-read','restore':'legacy-portable'}
    assert m['device']['uid'] == ['11223344','55667788']
    assert m['physicalRestorationQualifiedByThisExport'] is False
    assert m['bindings']['archivedPhysicalEvidence']['wholeFlashExact'] is True
    assert m['bindings']['archivedPhysicalEvidence']['performedByThisExport'] is False
    original = read_archive(args['restore'])
    for name,blob in original.items():
        assert files[name.removeprefix('legacy-portable/')] == blob
    evidence = json.loads(files['backup-result.json'])
    assert evidence['flash']['double_read_identical'] is True
    assert evidence['flash']['evidenceSource'] == 'recomputed by comparing both complete input dump copies'


@pytest.mark.parametrize('damage',['mismatched-double-read','inventory-hash','physical-flash','physical-uicr','extra-file','uid-mismatch','runtime-uicr-writer'])
def test_legacy_format_never_relaxes_binding_or_evidence_checks(legacy_sources,damage):
    args, _ = legacy_sources
    backup = read_archive(args['backup']); portable = read_archive(args['restore'])
    prefix = 'legacy-portable/'
    if damage == 'mismatched-double-read': backup['legacy-capture/flash-b.bin'] = bytes(0x100000)
    if damage == 'inventory-hash': portable[prefix+'restore_via_ble.py'] += b'# altered\n'
    if damage in ('physical-flash','physical-uicr'):
        report = json.loads(portable[prefix+'stock-restore-result.json'])
        if damage == 'physical-flash': report['flash_sha256'] = '0'*64
        else: report['uicr_exact'] = False
        portable[prefix+'stock-restore-result.json'] = json.dumps(report).encode()
        # Updating unsigned hash indexes cannot repair inconsistent historical evidence.
        m = json.loads(portable[prefix+'artifact-manifest.json'])
        m['physical_evidence']['stock-restore-result.json'] = sha(portable[prefix+'stock-restore-result.json'])
        portable[prefix+'artifact-manifest.json'] = json.dumps(m).encode()
        inventory = {name.removeprefix(prefix):dict(bytes=len(blob),sha256=sha(blob)) for name,blob in portable.items() if name!=prefix+'portable-inventory.json'}
        portable[prefix+'portable-inventory.json'] = json.dumps(inventory).encode()
    if damage == 'runtime-uicr-writer':
        checks = json.loads(portable[prefix+'effective-uicr-checks.json']); checks['restorer']['disable_flash_patch'] = 'y'
        portable[prefix+'effective-uicr-checks.json'] = json.dumps(checks).encode()
        inventory = {name.removeprefix(prefix):dict(bytes=len(blob),sha256=sha(blob)) for name,blob in portable.items() if name!=prefix+'portable-inventory.json'}
        portable[prefix+'portable-inventory.json'] = json.dumps(inventory).encode()
    if damage == 'extra-file': portable[prefix+'extra-private.key'] = b'unexpected'
    if damage == 'uid-mismatch':
        m = json.loads(portable[prefix+'artifact-manifest.json']);m['deviceid'][0]='deadbeef'
        portable[prefix+'artifact-manifest.json'] = json.dumps(m).encode()
    archive(args['backup'],backup);archive(args['restore'],portable)
    with pytest.raises(ValueError): package(args)
    assert not args['output'].exists()


def test_legacy_standalone_verifier_needs_no_original_prefix_or_repository(legacy_sources,tmp_path):
    import subprocess
    import sys
    args, _ = legacy_sources
    package(args)
    files = read_archive(args['output'])
    isolated = tmp_path/'isolated';isolated.mkdir()
    script = isolated/'verify-stock-recovery.py';script.write_bytes(files['verify-stock-recovery.py'])
    key = isolated/'signing-public.pem';key.write_bytes(files['signing-public.pem'])
    result = subprocess.run([sys.executable,str(script),'--verify',str(args['output']),'--public-key',str(key)],cwd=isolated,text=True,capture_output=True)
    assert result.returncode == 0,result.stderr
    assert json.loads(result.stdout)['signaturesAndBackupBindingsVerified'] is True


@pytest.mark.parametrize('form',['restorer','bootstrap'])
@pytest.mark.parametrize('mutation',['cmp-nop','refusal-branch','variant','literal-out-of-bounds','truncated-refusal'])
def test_resigned_legacy_guard_mutations_cannot_be_accepted(legacy_sources,form,mutation):
    args,key=legacy_sources
    files={name.removeprefix('legacy-portable/'):blob for name,blob in read_archive(args['restore']).items()}
    table=b''.join(hashlib.sha256(files['stock-flash.bin'][i:i+4096]).digest() for i in range(0,0x100000,4096))
    if form=='restorer':
        files['restorer.signed.bin']=signed(key,legacy_guard(form,mutation=mutation)+hashlib.sha256(files['stock-uicr.bin']).digest()+table,0xb0000)
        files['restore-bootstrap.signed.bin']=signed(key,legacy_guard('bootstrap')+files['restorer.signed.bin'],0xc000)
        h=IntelHex(io.StringIO(files['loader.hex'].decode()));h.puts(1024,hashlib.sha256(files['restorer.signed.bin']).digest());h.puts(1080,struct.pack('<I',len(files['restorer.signed.bin'])));text=io.StringIO();h.write_hex_file(text);files['loader.hex']=text.getvalue().encode()
    else:files['restore-bootstrap.signed.bin']=signed(key,legacy_guard(form,mutation=mutation)+files['restorer.signed.bin'],0xc000)
    m=json.loads(files['artifact-manifest.json'])
    for name in m['artifacts']:m['artifacts'][name]=dict(size=len(files[name]),sha256=sha(files[name]))
    files['artifact-manifest.json']=json.dumps(m).encode()
    files['portable-inventory.json']=json.dumps({name:dict(bytes=len(blob),sha256=sha(blob)) for name,blob in files.items() if name!='portable-inventory.json'}).encode()
    archive(args['restore'],{'legacy-portable/'+name:blob for name,blob in files.items()})
    with pytest.raises(ValueError):package(args)
    assert not args['output'].exists()


@pytest.mark.parametrize('form',['restorer','bootstrap'])
def test_thumb_guard_literal_bounds_are_checked_before_reading(form):
    from tools.firmware.package_stock_recovery import legacy_uid_guard_matches
    uid=(0x11223344,0x55667788)
    assert legacy_uid_guard_matches(legacy_guard(form),uid,0xafa7b332,form)
    assert not legacy_uid_guard_matches(legacy_guard(form,mutation='literal-out-of-bounds'),uid,0xafa7b332,form)
    assert not legacy_uid_guard_matches(legacy_guard(form,mutation='truncated-refusal'),uid,0xafa7b332,form)


@pytest.mark.parametrize('changed_payload',[False,True])
def test_legacy_bin_and_hex_may_have_distinct_signatures_only_for_the_same_authenticated_image(legacy_sources,changed_payload):
    args,key=legacy_sources
    files={name.removeprefix('legacy-portable/'):blob for name,blob in read_archive(args['restore']).items()}
    original=files['application.signed.bin'];payload_size=struct.unpack_from('<I',original,12)[0]
    payload=original[520:512+payload_size]+(b'changed' if changed_payload else b'')
    new=signed(key,payload,0xc000)
    assert new!=original
    h=IntelHex();h.frombytes(new,offset=0xc000);text=io.StringIO();h.write_hex_file(text)
    files['application.signed.hex']=text.getvalue().encode()
    m=json.loads(files['artifact-manifest.json'])
    m['artifacts']['application.signed.hex']=dict(size=len(files['application.signed.hex']),sha256=sha(files['application.signed.hex']))
    files['artifact-manifest.json']=json.dumps(m).encode()
    files['portable-inventory.json']=json.dumps({name:dict(bytes=len(blob),sha256=sha(blob)) for name,blob in files.items() if name!='portable-inventory.json'}).encode()
    archive(args['restore'],{'legacy-portable/'+name:blob for name,blob in files.items()})
    if changed_payload:
        with pytest.raises(ValueError):package(args)
        assert not args['output'].exists()
    else:
        package(args)
        assert args['output'].exists()
