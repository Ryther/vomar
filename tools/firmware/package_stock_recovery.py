#!/usr/bin/env python3
"""Consolidate an existing device-bound backup and pre-signed BLE restoration ZIP.

Host-only: no hardware access, key generation, signing, rewriting or deletion of
source archives. Refuses a consolidation unless backup identity, signed restore
bindings, source hashes and the externally selected public trust anchor agree.
The same file is included as the standalone offline verifier inside the archive.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import struct
import zipfile

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from intelhex import IntelHex

ROOT = Path(__file__).resolve().parents[2]
SIZES = {'flash': 0x100000, 'uicr': 4096, 'ficr': 4096}
DUMPS = {f'stock-{kind}.bin' for kind in SIZES}
BACKUP_FILES = DUMPS | {'backup-result.json'}
RESTORE_FILES = DUMPS | {'README.txt', 'artifact-manifest.json', 'restore-bootstrap.signed.bin',
    'restorer.signed.bin', 'loader.hex', 'recovery.signed.hex', 'signing-public.pem',
    'enter_restore_via_ble.py', 'restore_via_ble.py', 'research_console.py', 'logs/.keep'}
LEGACY_PORTABLE_FILES = set(('CMakeLists.txt',
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
 'update-images.hex'))
LEGACY_ARTIFACTS = {"initial-install.hex", "update-images.hex", "loader.hex", "application.signed.bin", "application.signed.hex",
    "recovery.signed.hex", "restorer.signed.bin", "restore-bootstrap.signed.bin", "signing-public.pem"}
PHYSICAL_REPORTS = {"application-ota-result.json", "stock-restore-result.json", "reinstallation-result.json", "uicr-restoration-result.json"}
ADDITIONS = {'manifest.json', 'RECOVERY-README.txt', 'requirements-restore.txt', 'verify-stock-recovery.py', 'logs/.keep'}
MAX_ZIP = 16 * 1024 * 1024
MAX_EXPANDED = 12 * 1024 * 1024
MAX_ENTRY = 2 * 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')


def parse_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON field: ' + key)
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('invalid JSON evidence') from error


def read_zip(path, expected=None):
    path = Path(path)
    if path.stat().st_size > MAX_ZIP:
        raise ValueError('archive exceeds compressed limit')
    data = path.read_bytes(); result = {}; total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for entry in archive.infolist():
                mode = entry.external_attr >> 16
                if ((expected is not None and entry.filename not in expected) or entry.filename in result or entry.is_dir()
                        or entry.filename.startswith("/") or "\\" in entry.filename or any(part in ("", ".", "..") for part in entry.filename.split("/"))
                        or entry.flag_bits & 1 or mode & 0xf000 not in (0, 0x8000)):
                    raise ValueError('unexpected, duplicate, encrypted or nonregular ZIP entry')
                if not 0 <= entry.file_size <= MAX_ENTRY or total + entry.file_size > MAX_EXPANDED:
                    raise ValueError('archive exceeds expanded limit')
                with archive.open(entry) as stream:
                    blob = stream.read(min(MAX_ENTRY, MAX_EXPANDED - total) + 1)
                if len(blob) != entry.file_size:
                    raise ValueError('archive entry size mismatch')
                result[entry.filename] = blob; total += len(blob)
    except (zipfile.BadZipFile, RuntimeError, EOFError) as error:
        raise ValueError('invalid or corrupt ZIP') from error
    if expected is not None and set(result) != expected:
        raise ValueError('archive is missing required entries')
    return result, sha(data)


def read_backup_source(path, source_format):
    if source_format == 'schema1':
        return read_zip(path, BACKUP_FILES)
    if source_format != 'legacy-double-read':
        raise ValueError('unsupported backup source format')
    entries, digest = read_zip(path)
    parts = [name.split('/') for name in entries]
    if not parts or any(len(row) != 2 for row in parts) or len({row[0] for row in parts}) != 1:
        raise ValueError('legacy backup requires one explicit prefix and exactly six dump files')
    prefix = parts[0][0] + '/'
    expected = {prefix + kind + '-' + suffix + '.bin' for kind in SIZES for suffix in ('a', 'b')}
    if set(entries) != expected:
        raise ValueError('legacy backup requires exactly two complete FLASH/UICR/FICR copies')
    files = {}; evidence = {}
    for kind, size in SIZES.items():
        a = entries[prefix + kind + '-a.bin']; b = entries[prefix + kind + '-b.bin']
        if len(a) != size or a != b:
            raise ValueError('legacy double-read copies differ or are incomplete: ' + kind)
        files['stock-' + kind + '.bin'] = a
        evidence[kind] = dict(size=size, sha256=sha(a), double_read_identical=True,
            evidenceSource='recomputed by comparing both complete input dump copies',
            sourceEntries=[prefix + kind + '-a.bin', prefix + kind + '-b.bin'])
    files['backup-result.json'] = canonical(evidence)
    return files, digest


def read_restore_source(path, source_format):
    if source_format == 'schema1':
        return read_zip(path, RESTORE_FILES)
    if source_format != 'legacy-portable':
        raise ValueError('unsupported restoration source format')
    entries, digest = read_zip(path)
    prefixes = {name.split('/', 1)[0] for name in entries}
    if len(prefixes) != 1:
        raise ValueError('legacy portable archive requires one explicit prefix')
    prefix = next(iter(prefixes)) + '/'
    if set(entries) != {prefix + name for name in LEGACY_PORTABLE_FILES}:
        raise ValueError('legacy portable archive file inventory differs from supported format')
    return {name[len(prefix):]: data for name, data in entries.items()}, digest


def validate_portable_inventory(restore):
    if set(restore) != LEGACY_PORTABLE_FILES:
        raise ValueError('incomplete legacy portable files')
    inventory = parse_json(restore['portable-inventory.json'])
    if not isinstance(inventory, dict) or set(inventory) != LEGACY_PORTABLE_FILES - {'portable-inventory.json'}:
        raise ValueError('incomplete legacy portable inventory')
    for name, row in inventory.items():
        if row != dict(bytes=len(restore[name]), sha256=sha(restore[name])):
            raise ValueError('legacy portable inventory hash/size mismatch: ' + name)


def load_public_key(data):
    try:
        key = serialization.load_pem_public_key(data)
    except ValueError:
        key = serialization.load_der_public_key(data)
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError('ECDSA P256 public trust anchor required')
    return key


def public_der(key):
    return key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def tlvs(data, start, magic):
    if start + 4 > len(data):
        raise ValueError('truncated TLV area')
    actual, length = struct.unpack_from('<HH', data, start)
    end = start + length
    if actual != magic or length < 4 or end > len(data):
        raise ValueError('invalid TLV area')
    result = {}; offset = start + 4
    while offset < end:
        if offset + 4 > end:
            raise ValueError('truncated TLV record')
        tag, size = struct.unpack_from('<HH', data, offset); offset += 4
        if tag in result or size > end - offset:
            raise ValueError('duplicate or truncated TLV record')
        result[tag] = data[offset:offset + size]; offset += size
    return result, end


def signed_image(data, key, base, capacity, *, allow_rom_fixed=False):
    if not 520 <= len(data) <= capacity or struct.unpack_from('<I', data)[0] != 0x96f3b83d:
        raise ValueError('invalid signed image geometry')
    header, protected, payload, flags = struct.unpack_from('<HHII', data, 8)
    load = struct.unpack_from('<I', data, 4)[0]
    # Legacy recovery.signed.hex uses MCUboot IMAGE_F_ROM_FIXED at its exact slot.
    valid_flags = (flags == 0 and load == 0) or (allow_rom_fixed and flags == 0x100 and load == base)
    if header != 512 or payload < 8 or not valid_flags or struct.unpack_from('<I', data, 28)[0]:
        raise ValueError('unsupported signed image header')
    end = header + payload
    if end > len(data):
        raise ValueError('truncated signed image')
    if protected:
        _, protected_end = tlvs(data, end, 0x6908)
        if protected_end != end + protected:
            raise ValueError('protected TLV length mismatch')
        end = protected_end
    ordinary, full_end = tlvs(data, end, 0x6907)
    if full_end != len(data) or set(ordinary) != {1, 0x10, 0x22}:
        raise ValueError('unexpected unsigned TLVs or trailing image bytes')
    if ordinary[1] != hashlib.sha256(public_der(key)).digest() or ordinary[0x10] != hashlib.sha256(data[:end]).digest():
        raise ValueError('image digest or pinned public-key hash mismatch')
    try:
        key.verify(ordinary[0x22], data[:end], ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError) as error:
        raise ValueError('image signature invalid') from error
    stack, reset = struct.unpack_from('<II', data, header)
    if not 0x20000000 < stack <= 0x20040000 or stack % 8 or not reset & 1 or not base + header <= (reset & ~1) < base + header + payload:
        raise ValueError('image vectors outside authorized SRAM/slot')
    return data[header:end], sha(data[:end])


def hex_region(data, low, high):
    try:
        image = IntelHex(io.StringIO(data.decode('ascii')))
    except Exception as error:
        raise ValueError('invalid Intel HEX artifact') from error
    addresses = image.addresses()
    if not addresses or min(addresses) < low or max(addresses) >= high:
        raise ValueError('Intel HEX addresses outside authorized region')
    return bytes(image.tobinarray(start=low, end=max(addresses))), image


def legacy_uid_guard_matches(payload, uid, variant, form):
    """Recognize only the two audited legacy Thumb guard forms, not arbitrary code.

    The compiler reuses the variant constant to form UID0 through three adds.
    Literal-presence scans cannot establish this form. Every FICR load, compare,
    refusal branch and bounded literal below is required. This is a supported
    compiler-pattern check, not proof of whole-program behavior or attestation.
    """
    def word(at):
        if at < 0 or at + 2 > len(payload):
            raise ValueError('truncated Thumb guard')
        return struct.unpack_from('<H', payload, at)[0]

    def literal(at, register):
        ins = word(at)
        if ins & 0xf800 != 0x4800 or (ins >> 8) & 7 != register:
            raise ValueError('unexpected Thumb literal load')
        target = ((at + 4) & ~3) + (ins & 255) * 4
        if target + 4 > len(payload):
            raise ValueError('Thumb literal outside authenticated payload')
        return struct.unpack_from('<I', payload, target)[0]

    def conditional(at, condition):
        ins = word(at)
        if (ins & 0xff00) != (0xd000 | (condition << 8)):
            raise ValueError('unexpected Thumb refusal branch')
        immediate = ins & 255
        if immediate & 128:
            immediate -= 256
        target = at + 4 + immediate * 2
        if target < 0 or target + 2 > len(payload):
            raise ValueError('Thumb branch outside authenticated payload')
        return target

    def bl(at):
        return word(at) & 0xf800 == 0xf000 and word(at + 2) & 0xd000 == 0xd000

    if form not in ('restorer', 'bootstrap'):
        return False
    constant, loaded, prefix_size = (1, 0, 18) if form == 'restorer' else (2, 1, 14)
    variant_load = bytes.fromhex('d3f80401' if form == 'restorer' else 'd3f80411')
    cmp_uid = 0x4280 | (constant << 3) | loaded
    add_first = bytes.fromhex('01f1c241' if form == 'restorer' else '02f1c242')
    add_second = bytes.fromhex('01f5f501' if form == 'restorer' else '02f5f502')
    if (variant + 0x61000000 + 0x7a8000 + 0x12) & 0xffffffff != uid[0]:
        return False
    for at in range(prefix_size, len(payload) - 34, 2):
        if payload[at:at + 4] != variant_load:
            continue
        try:
            start = at - prefix_size
            if payload[start:start + 4] != bytes.fromhex('4ff08053') or literal(start + 4, 2) != 0x52840:
                continue
            if payload[start + 6:start + 10] != bytes.fromhex('d3f80011') or word(start + 10) != 0x4291:
                continue
            refusal = conditional(at + 8, 1)
            if form == 'restorer':
                if word(start + 12) != 0xb08f or not 0x20000000 <= literal(start + 14, 2) < 0x20040000:
                    continue
                if conditional(start + 16, 1) != refusal:
                    continue
            elif conditional(start + 12, 1) != refusal:
                continue
            if literal(at + 4, constant) != variant or word(at + 6) != cmp_uid:
                continue
            if payload[at + 10:at + 14] != add_first or word(at + 14) != (0x6e18 | loaded):
                continue
            if payload[at + 16:at + 20] != add_second or word(at + 20) != (0x3012 | (constant << 8)):
                continue
            if word(at + 22) != cmp_uid or conditional(at + 24, 1) != refusal:
                continue
            if word(at + 26) != (0x6e58 | constant) or literal(at + 28, 3) != uid[1] or word(at + 30) != (0x4298 | constant):
                continue
            if form == 'restorer':
                if conditional(at + 32, 1) != refusal or refusal < at + 34:
                    continue
                if payload[refusal:refusal + 4] != bytes.fromhex('00231370'):
                    continue
                literal(refusal + 4, 2); literal(refusal + 6, 0)
                if word(refusal + 8) != 0x2101 or not bl(refusal + 10):
                    continue
                if payload[refusal + 14:refusal + 22] != bytes.fromhex('00200fb05df804fb'):
                    continue
            else:
                if refusal != at + 34 or conditional(at + 32, 0) != refusal + 14:
                    continue
                literal(refusal, 2); literal(refusal + 2, 0)
                if word(refusal + 4) != 0x2101 or not bl(refusal + 6):
                    continue
                if payload[refusal + 10:refusal + 14] != bytes.fromhex('002070bd'):
                    continue
            return True
        except (ValueError, struct.error):
            continue
    return False


def validate_sources(backup, restore, trusted, restore_format='schema1'):
    for kind, size in SIZES.items():
        name = f'stock-{kind}.bin'
        if len(backup[name]) != size or restore[name] != backup[name]:
            raise ValueError('backup/restore dump size or byte mismatch: ' + kind)
    evidence = parse_json(backup['backup-result.json'])
    if not isinstance(evidence, dict) or set(evidence) != set(SIZES):
        raise ValueError('incomplete backup evidence')
    for kind, size in SIZES.items():
        row = evidence[kind]
        if row.get('size') != size or row.get('sha256') != sha(backup[f'stock-{kind}.bin']) or row.get('double_read_identical') is not True:
            raise ValueError('backup hash/double-read evidence mismatch: ' + kind)
    flash, uicr, ficr = (backup[f'stock-{kind}.bin'] for kind in ('flash', 'uicr', 'ficr'))
    uid = struct.unpack_from('<II', ficr, 0x60)
    part, variant = struct.unpack_from('<II', ficr, 0x100)
    if part != 0x52840 or variant in (0, 0xffffffff) or any(word in (0, 0xffffffff) for word in uid):
        raise ValueError('unsupported or missing FICR identity')
    if flash[0xb0000:0xef000] != b'\xff' * 0x3f000:
        raise ValueError('stock scratch region is not entirely erased')
    m = parse_json(restore['artifact-manifest.json'])
    if m.get('deviceid') != [f'{word:08x}' for word in uid] or m.get('flash_sha256') != sha(flash) or m.get('uicr_sha256') != sha(uicr):
        raise ValueError('restore manifest UID/backup binding mismatch')
    if restore_format == 'legacy-portable':
        validate_portable_inventory(restore)
        artifacts = LEGACY_ARTIFACTS
        source = parse_json(restore['source-manifest.json'])
        if any(source.get(name) != m.get(name) for name in ('deviceid', 'variant', 'flash_sha256', 'uicr_sha256')):
            raise ValueError('legacy source/artifact identity bindings differ')
        if m.get('variant') != f'{variant:08x}':
            raise ValueError('legacy variant does not match FICR')
        checks = parse_json(restore['effective-uicr-checks.json'])
        if set(checks) != {'main', 'mcuboot', 'recovery', 'restorer', 'bootstrap'} or any(
                row.get('disable_flash_patch') != 'n' or row.get('startup_uicr_macros') != [] or row.get('disable_flash_patch_symbol') is not False
                for row in checks.values()):
            raise ValueError('legacy package is not the corrected no-UICR-writer revision')
        if set(m.get('physical_evidence', {})) != PHYSICAL_REPORTS:
            raise ValueError('legacy physical evidence inventory is incomplete')
        for name, digest in m['physical_evidence'].items():
            if sha(restore[name]) != digest:
                raise ValueError('legacy physical evidence hash mismatch: ' + name)
        physical = parse_json(restore['stock-restore-result.json'])
        original_uicr = parse_json(restore['uicr-restoration-result.json'])
        if (any(physical.get(field) is not True for field in ('whole_flash_exact', 'uicr_exact', 'ficr_exact', 'runtime_uicr_original'))
                or physical.get('flash_sha256') != sha(flash) or original_uicr.get('uicr_sha256') != sha(uicr)):
            raise ValueError('legacy physical restore evidence is not bound to this backup')
    elif restore_format == 'schema1':
        artifacts = {'restorer.signed.bin', 'restore-bootstrap.signed.bin', 'loader.hex', 'recovery.signed.hex', 'signing-public.pem'}
        expected_package = RESTORE_FILES - {'artifact-manifest.json', 'logs/.keep'}
        if set(m.get('package_files', {})) != expected_package:
            raise ValueError('incomplete source restoration package manifest')
        for name, digest in m['package_files'].items():
            if sha(restore[name]) != digest:
                raise ValueError('source restoration package hash mismatch: ' + name)
    else:
        raise ValueError('unsupported restoration source format')
    if set(m.get('artifacts', {})) != artifacts:
        raise ValueError('incomplete signed artifact manifest')
    for name, row in m['artifacts'].items():
        if row.get('size') != len(restore[name]) or row.get('sha256') != sha(restore[name]):
            raise ValueError('source artifact digest/size mismatch: ' + name)
    for name, blob in restore.items():
        if name not in DUMPS and re.search(rb'-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----', blob):
            raise ValueError('private key material in source archive')
    key = load_public_key(restore['signing-public.pem'])
    if public_der(key) != public_der(trusted):
        raise ValueError('source signing public key differs from pinned trust anchor')
    restorer = restore['restorer.signed.bin']
    restorer_region, restorer_signed_hash = signed_image(restorer, trusted, 0xb0000, 0x3f000)
    bridge_region, _ = signed_image(restore['restore-bootstrap.signed.bin'], trusted, 0xc000, 0xa4000)
    uid_bytes = struct.pack('<II', *uid)
    table = b''.join(hashlib.sha256(flash[offset:offset + 4096]).digest() for offset in range(0, len(flash), 4096))
    if table not in restorer_region:
        raise ValueError('signed restorer does not contain the exact stock page-hash table')
    if hashlib.sha256(uicr).digest() not in restorer_region:
        raise ValueError('signed restorer UICR binding mismatch')
    if restore_format == 'legacy-portable':
        if not legacy_uid_guard_matches(restorer_region, uid, variant, 'restorer') or not legacy_uid_guard_matches(bridge_region, uid, variant, 'bootstrap'):
            raise ValueError('legacy signed FICR/UID refusal guard is unsupported or malformed')
    elif uid_bytes not in restorer_region or uid_bytes not in bridge_region:
        raise ValueError('signed restoration artifacts do not bind the FICR UID words')
    if restorer not in bridge_region:
        raise ValueError('signed bootstrap does not embed the exact signed restorer')
    loader_region, loader_hex = hex_region(restore['loader.hex'], 0, 0xc000)
    if hashlib.sha256(restorer).digest() not in loader_region or struct.pack('<I', len(restorer)) not in loader_region:
        raise ValueError('loader does not contain the exact restorer authorization digest/size')
    recovery, _ = hex_region(restore['recovery.signed.hex'], 0xb0000, 0xf0000)
    _, recovery_signed_hash = signed_image(recovery, trusted, 0xb0000, 0x40000, allow_rom_fixed=True)
    result = dict(uid=[f'{word:08x}' for word in uid], part=part, variant=variant,
                publicKeySpkiSha256=sha(public_der(trusted)), restorerSignedRegionSha256=restorer_signed_hash,
                entryRecoverySignedRegionSha256=recovery_signed_hash,
                requiredLoaderRegionSha256=sha(bytes(loader_hex.tobinarray(start=0, end=0xbfff))),
                originalRestorationStatus=m.get('status', 'not recorded'))
    if restore_format == 'legacy-portable':
        _, bin_signed_hash = signed_image(restore['application.signed.bin'], trusted, 0xc000, 0xa4000)
        application, _ = hex_region(restore['application.signed.hex'], 0xc000, 0xb0000)
        _, hex_signed_hash = signed_image(application, trusted, 0xc000, 0xa4000)
        if hex_signed_hash != bin_signed_hash:
            raise ValueError('legacy application HEX/BIN authenticated regions differ')
        for name in ('initial-install.hex', 'update-images.hex'):
            hex_region(restore[name], 0, 0x100000)
        result['sourcePackageFormat'] = 'legacy-portable'
        result['uidBindingEvidence'] = 'audited Thumb FICR guards: exact base/part/variant, arithmetic UID0, UID1, common refusal branches'
        result['archivedPhysicalEvidence'] = dict(wholeFlashExact=True, uicrExact=True, ficrExact=True,
            flashSha256=sha(flash), evidenceSha256=sha(restore['stock-restore-result.json']), performedByThisExport=False,
            scope='historical nRF52840 bench restore; no light, external memory or secondary MCU proof')
    return result


def readme(binding):
    uid = ':'.join(binding['uid'])
    source_readme = 'README.md' if binding.get('sourcePackageFormat') == 'legacy-portable' else 'README.txt'
    return f'''PRIVATE COMPLETE STOCK RECOVERY — UID {uid}

Keep this ONE ZIP per device. The same FLASH/UICR/FICR files serve offline/SWD
recovery and the already signed BLE restoration material. No separate identity
file, name/room record, private signing key or firmware rebuild is required.
Keep the returned ZIP SHA256 with a trusted project record if available.
This export verifies bytes/signatures/bindings; it does not test physical restore.

OFFLINE CHECK (no hardware): extract to a private directory, then run
  python verify-stock-recovery.py --verify /path/to/this.zip --public-key signing-public.pem
The public key included here matched the explicitly pinned project trust anchor
at export. When checking material from an untrusted source, use the public key
from your trusted project checkout instead. The consolidation manifest is an
unsigned index; the original firmware artifacts retain their signatures.
Install requirements-restore.txt in an isolated Python environment if necessary.

SWD ROUTE — requires a separately authorized hardware restoration operation:
stock-flash.bin covers address0x00000000 through0x000FFFFF, including stock
bootloader, application, network/settings and other original nRF52840 FLASH.
stock-uicr.bin preserves4096 bytes at0x10001000; compare it before/after restoration.
BLE restoration requires UICR unchanged and never writes it. If UICR differs,
that is a separate explicitly authorized repair; this export does not perform it.
stock-ficr.bin preserves4096 bytes at0x10000000 as factory identity evidence.
FICR is factory read-only: NEVER program it. The secondary power MCU is outside
this backup's scope. Restore/read back the exact intended nRF target through a
qualified SWD workflow; compare all FLASH bytes and UICR against these dumps.
No erase/recover/program command is executed by this export or offline check.

EXISTING BLE ROUTE — pre-signed materials, not an Android RESTORE import feature:
{source_readme}, enter_restore_via_ble.py, restore_via_ble.py, research_console.py,
restorer.signed.bin, restore-bootstrap.signed.bin, loader.hex, recovery.signed.hex
and artifact-manifest.json retain their original filenames and exact bytes.
Their Linux/BlueZ instructions remain in {source_readme} and require separate approval
before running an operation that rewrites hardware. logs/.keep preserves the
working directory required by the clients. No Nordic SDK/build/signing key is
needed for these pre-signed artifacts. The entry tool requires the exact recorded
entry recovery; the loader's recorded restorer authorization must still apply.
Do not assume compatibility with a future/new generic loader or another unit.

Recorded source qualification: {binding['originalRestorationStatus']}
The full SWD dumps remain available even when that BLE entry path is unavailable.
Future phone-created raw backup ZIPs may have no pre-signed BLE helper yet; they
are a different capability and must not be labelled equivalent BLE restore kits.
'''.encode('utf-8')


def scope_records(files):
    scope = {}
    for kind, address in [('flash', 0), ('uicr', 0x10001000), ('ficr', 0x10000000)]:
        scope[kind] = dict(address=address, size=SIZES[kind], file=f'stock-{kind}.bin', sha256=sha(files[f'stock-{kind}.bin']),
            restore={'flash': 'complete original nRF52840 FLASH; separately authorized SWD or compatible recorded BLE path',
                     'uicr': 'preserved backup; BLE verifies unchanged and never writes',
                     'ficr': 'factory-read-only; identity evidence; never program'}[kind])
    return scope


def verify_stock_recovery_archive(path, public_key_path):
    files, digest = read_zip(path)
    manifest = parse_json(files['manifest.json'])
    if type(manifest.get('schemaVersion')) is not int or manifest['schemaVersion'] != 1 or manifest.get('kind') != 'private-stock-recovery':
        raise ValueError('unsupported consolidated recovery archive')
    formats = manifest.get('sourceFormats', dict(backup='schema1', restore='schema1'))
    if formats.get('backup') not in ('schema1', 'legacy-double-read') or formats.get('restore') not in ('schema1', 'legacy-portable'):
        raise ValueError('unsupported consolidated source formats')
    restore_names = LEGACY_PORTABLE_FILES if formats['restore'] == 'legacy-portable' else RESTORE_FILES
    if set(files) != BACKUP_FILES | restore_names | ADDITIONS:
        raise ValueError('consolidated file inventory differs from supported source format')
    if manifest.get('scope') != scope_records(files) or manifest.get('physicalRestorationQualifiedByThisExport') is not False or manifest.get('secondaryMcuIncluded') is not False:
        raise ValueError('consolidated scope/qualification claims do not match verified coverage')
    expected = set(files) - {'manifest.json'}
    if set(manifest.get('files', {})) != expected:
        raise ValueError('consolidated manifest file inventory mismatch')
    for name, row in manifest['files'].items():
        if row != dict(size=len(files[name]), sha256=sha(files[name])):
            raise ValueError('consolidated file hash mismatch: ' + name)
    binding = validate_sources({name: files[name] for name in BACKUP_FILES},
                               {name: files[name] for name in restore_names},
                               load_public_key(Path(public_key_path).read_bytes()), formats['restore'])
    expected_device = dict(soc='nRF52840', uid=binding['uid'], uidSource=dict(file='stock-ficr.bin', offset=0x60, wordCount=2, encoding='uint32 little-endian'))
    if manifest.get('device') != expected_device or manifest.get('bindings') != binding:
        raise ValueError('consolidated identity/binding index mismatch')
    return dict(path=str(Path(path).resolve()), sha256=digest, uid=binding['uid'],
                signaturesAndBackupBindingsVerified=True, physicalRestorationQualified=False)


def create_stock_recovery_archive(backup, restore, public_key, output, *, backup_format='schema1', restore_format='schema1'):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to(ROOT / 'inputs'):
        raise ValueError('output must be new and outside immutable inputs')
    backup_files, backup_digest = read_backup_source(backup, backup_format)
    restore_files, restore_digest = read_restore_source(restore, restore_format)
    trusted = load_public_key(Path(public_key).read_bytes())
    binding = validate_sources(backup_files, restore_files, trusted, restore_format)
    files = {**backup_files, **restore_files, 'logs/.keep': restore_files.get('logs/.keep', b''),
             'RECOVERY-README.txt': readme(binding),
             'requirements-restore.txt': b'cryptography\nintelhex\nbleak\nsmpclient\ndbus-fast\n',
             'verify-stock-recovery.py': Path(__file__).read_bytes()}
    scope = scope_records(files)
    manifest = dict(schemaVersion=1, kind='private-stock-recovery', device=dict(soc='nRF52840', uid=binding['uid'],
                    uidSource=dict(file='stock-ficr.bin', offset=0x60, wordCount=2, encoding='uint32 little-endian')),
                    scope=scope, secondaryMcuIncluded=False, physicalRestorationQualifiedByThisExport=False,
                    manifestAuthentication='unsigned consolidation index; original image signatures verified against explicit pinned public key',
                    inputs=dict(stockBackupSha256=backup_digest, bleStockRestoreSha256=restore_digest), bindings=binding,
                    verification=dict(doubleReadEvidencePreserved=True, signedRestorerPageTableMatchesAll256Pages=True,
                        signedRestorerUicrDigestMatches=True, uidWordsBoundInAuthenticatedRestorerAndBootstrap=True,
                        signedBootstrapEmbedsExactSignedRestorer=True, loaderContainsRestorerAuthorizationDigestAndSize=True,
                        scope='byte/cryptographic binding verification; no execution/control-flow or physical restore test'),
                    files={name: dict(size=len(data), sha256=sha(data)) for name, data in files.items()})
    if backup_format != 'schema1' or restore_format != 'schema1':
        manifest['sourceFormats'] = dict(backup=backup_format, restore=restore_format)
    files['manifest.json'] = canonical(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in ['manifest.json', 'RECOVERY-README.txt', *sorted(set(files) - {'manifest.json', 'RECOVERY-README.txt'})]:
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)); entry.external_attr = 0o100600 << 16
            archive.writestr(entry, files[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    data = buffer.getvalue()
    if len(data) > MAX_ZIP:
        raise ValueError('consolidated archive exceeds limit')
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as destination:
        destination.write(data); destination.flush(); os.fsync(destination.fileno())
    # Independent reopen validates the final ZIP and every cross-binding again.
    result = verify_stock_recovery_archive(output, public_key)
    result['sources'] = dict(stockBackupSha256=backup_digest, bleStockRestoreSha256=restore_digest)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--restore', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--public-key', type=Path, required=True)
    parser.add_argument('--verify', type=Path)
    parser.add_argument('--backup-format', choices=('schema1','legacy-double-read'), default='schema1')
    parser.add_argument('--restore-format', choices=('schema1','legacy-portable'), default='schema1')
    args = parser.parse_args()
    if args.verify:
        if any((args.backup, args.restore, args.output)):
            parser.error('--verify cannot be combined with packaging inputs')
        result = verify_stock_recovery_archive(args.verify, args.public_key)
    else:
        if not all((args.backup, args.restore, args.output)):
            parser.error('--backup, --restore and --output are required for consolidation')
        result = create_stock_recovery_archive(args.backup, args.restore, args.public_key, args.output, backup_format=args.backup_format, restore_format=args.restore_format)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
