#!/usr/bin/env python3
"""Read-only offline verifier for DkBackupArchive's exact five-entry ZIP.

No extraction, target access, signing, restore execution or source rewriting.
Hashes/FICR/geometry/vectors are independently checked from exported bytes.
Two acquisition passes, live identity checks and absence of target writes are
producer-reported claims: a single exported copy cannot independently prove them.
Optional prior comparison reads only its three stock-*.bin dump members; it
does not authenticate or qualify that prior archive's BLE restoration material.
"""
import argparse
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import sys
import zipfile
import zlib


REGIONS = (('flash.bin', 0, 0x100000), ('ficr.bin', 0x10000000, 4096),
           ('uicr.bin', 0x10001000, 4096))
ENTRY_LIMITS = {name: size for name, _, size in REGIONS} | {'manifest.json': 65536, 'README.txt': 8192}
MAX_ZIP = 2 * 1024 * 1024
MAX_EXPANDED = sum(ENTRY_LIMITS.values())
PRIOR_MAX_ZIP, PRIOR_MAX_EXPANDED, PRIOR_MAX_ENTRY = 16 * 1024 * 1024, 12 * 1024 * 1024, 2 * 1024 * 1024
SHA256 = re.compile(r'[0-9a-f]{64}')
WORD_HEX = re.compile(r'0x[0-9a-f]{8}')

# Public immutable input fingerprints, not proprietary bytes or per-device IDs.
# Same source registry as DkPublicStockApplications in DkBackupArchive.kt.
STOCK_APPLICATIONS = (
    dict(id='vimar-30805-mesh', model='VIMAR30805', radio='mesh', offset=0x26000, size=213012,
         sha256='8c0408c49fe3e35758a69e511faa154c2f1237512e1c1bfdf1061221db53f927'),
    dict(id='vimar-30805-zigbee', model='VIMAR30805', radio='zigbee', offset=0x26000, size=343988,
         sha256='710f788a02eca3985d5826efacf47cef8d8fa29dde4684815c25c8c9a79690d5'),
)
PROTOCOL = dict(id='jlink-raw-swd-ap0-read-v1', swdClockKhz=100, maxBlockBytes=512,
                tarBoundaryBytes=1024, independentBlockSentinels=True)
SCOPE = dict(haltAttempted=False, resetAttempted=False, eraseAttempted=False, memoryWrite=False,
             flashed=False, targetSupplyChanged=False, debugPortConfigured=True, restorationVerified=False)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def record(value, names, label):
    require(type(value) is dict and set(value) == set(names), 'Unexpected ' + label + ' schema')


def literal_record(value, expected, label):
    record(value, expected, label)
    require(all(type(value[key]) is type(wanted) and value[key] == wanted for key, wanted in expected.items()),
            'Unsupported ' + label + ' values')


def strict_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON field: ' + key)
            result[key] = value
        return result

    def invalid_constant(_):
        raise ValueError('Nonfinite JSON value')

    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=unique, parse_constant=invalid_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError('Invalid UTF-8 JSON manifest') from error


def read_archive(path, *, prior=False):
    """Bound headers before decompressing; a prior archive's other data is unread."""
    maximum = PRIOR_MAX_ZIP if prior else MAX_ZIP
    with Path(path).open('rb') as source:
        data = source.read(maximum + 1)
    require(0 < len(data) <= maximum, 'Archive exceeds compressed limit or is empty')
    if not prior:
        # ZipOutputStream emits neither an executable prefix, ZIP comment nor
        # trailing bytes. Keep those outside the supported five-entry contract.
        require(data.startswith(b'PK\x03\x04') and len(data) >= 22 and data[-22:-18] == b'PK\x05\x06',
                'Unsupported Android ZIP framing')
        disk, central_disk, disk_count, count, central_size, central_start, comment = struct.unpack_from('<4H2IH', data, len(data) - 18)
        require(disk == central_disk == 0 and disk_count == count == 5 and comment == 0
                and central_start + central_size == len(data) - 22
                and data[central_start:central_start + 4] == b'PK\x01\x02', 'Unsupported Android ZIP directory framing')
    selected = {}; names = set(); total = 0
    wanted = {'stock-' + name for name, _, _ in REGIONS} if prior else set(ENTRY_LIMITS)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            require(len(infos) <= (128 if prior else 5), 'Archive entry count exceeds limit')
            for info in infos:
                name = info.filename; mode = info.external_attr >> 16
                require(name == info.orig_filename and name not in names and not info.is_dir()
                        and not name.startswith('/') and '\\' not in name
                        and all(part not in ('', '.', '..') for part in name.split('/'))
                        and not info.flag_bits & 1 and mode & 0xf000 in (0, 0x8000)
                        and not info.external_attr & 0x10,
                        'Unexpected, duplicate, encrypted or nonregular ZIP entry')
                require(info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'Unsupported ZIP compression')
                require(prior or name in wanted, 'Unexpected Android backup entry: ' + name)
                limit = PRIOR_MAX_ENTRY if prior else ENTRY_LIMITS[name]
                total += info.file_size
                require(0 <= info.file_size <= limit and total <= (PRIOR_MAX_EXPANDED if prior else MAX_EXPANDED),
                        'Archive exceeds expanded limit')
                names.add(name)
                if name not in wanted:
                    continue
                if prior:
                    limit = next(size for region, _, size in REGIONS if name == 'stock-' + region)
                require(0 < info.file_size <= limit, 'Invalid member length: ' + name)
                with archive.open(info) as stream:
                    blob = stream.read(limit + 1)
                require(len(blob) == info.file_size and len(blob) <= limit, 'ZIP member length mismatch: ' + name)
                selected[name] = blob
    except (zipfile.BadZipFile, RuntimeError, EOFError, zlib.error, NotImplementedError) as error:
        raise ValueError('Invalid or corrupt ZIP archive') from error
    require(set(selected) == wanted and (prior or names == wanted), 'Archive is missing required entries')
    return selected, sha(data)


def timestamp(value):
    require(type(value) is str, 'Invalid timestamp type')
    match = re.fullmatch(r'([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.([0-9]{1,9}))?Z', value)
    require(match is not None, 'Invalid UTC timestamp')
    try:
        base = datetime.strptime(match[1], '%Y-%m-%dT%H:%M:%S')
    except ValueError as error:
        raise ValueError('Invalid UTC timestamp') from error
    return base, int((match[2] or '').ljust(9, '0'))


def validate_provenance(value):
    record(value, ('appVersion', 'probeFirmware', 'usbVendorId', 'usbProductId', 'interfaceId',
                   'inputEndpoint', 'outputEndpoint', 'targetMillivolts'), 'provenance')
    for key, limit in [('appVersion', 128), ('probeFirmware', 1024)]:
        require(type(value[key]) is str and bool(value[key].strip()) and len(value[key]) <= limit,
                'Invalid provenance ' + key)
    for key in set(value) - {'appVersion', 'probeFirmware'}:
        require(type(value[key]) is int, 'Invalid provenance integer: ' + key)
    require(value['usbVendorId'] == 0x1366 and value['usbProductId'] == 0x1060 and value['interfaceId'] >= 0
            and 0x81 <= value['inputEndpoint'] <= 0x8f and 1 <= value['outputEndpoint'] <= 15
            and 1700 <= value['targetMillivolts'] <= 3600, 'Unsupported USB/probe provenance')


def verify_backup(backup, compare_stock_recovery=None):
    entries, digest = read_archive(backup)
    manifest = strict_json(entries['manifest.json'])
    halted = type(manifest) is dict and manifest.get('type') == 'nrf52840-quiescent-first-install-backup'
    record(manifest, ('schema', 'type', 'target', 'byteExactDoubleRead', 'startedAt', 'verifiedAt',
                      'snapshotAtomic', 'protocol', 'scope', 'provenance', 'regions') + (('acquisition',) if halted else ()), 'manifest')
    require(type(manifest['schema']) is int and manifest['schema'] == 1
            and (halted or manifest['type'] == 'nrf52840-read-only-double-backup'), 'Unsupported Android backup contract')
    require(manifest['byteExactDoubleRead'] is True and manifest['snapshotAtomic'] is False,
            'Unsupported double-read/non-atomic snapshot claims')
    require(timestamp(manifest['verifiedAt']) >= timestamp(manifest['startedAt']), 'Verification timestamp precedes start')
    protocol, scope = dict(PROTOCOL), dict(SCOPE)
    if halted:
        a = manifest['acquisition']
        optional_watchdog = ('watchdog',) if type(a) is dict and 'watchdog' in a else ()
        record(a, ('cpuHalted', 'method', 'originalCpuControl') + optional_watchdog, 'quiescent acquisition')
        require(a['cpuHalted'] is True and type(a['method']) is str and a['method'] in ('debug-halt', 'reset-vector-catch')
                and type(a['originalCpuControl']) is int and a['originalCpuControl'] in (0, 1, 3), 'Unsupported quiescent acquisition')
        if optional_watchdog:
            w = a['watchdog']; record(w, ('runStatus', 'config', 'crv', 'rren'), 'watchdog observation')
            require(all(type(value) is int for value in w.values())
                    and w['runStatus'] in (0, 1) and 0 <= w['config'] <= 0xffffffff and w['config'] & ~9 == 0
                    and 0 <= w['crv'] <= 0xffffffff and 0 <= w['rren'] <= 255, 'Invalid watchdog observation')
            require(w['runStatus'] == 0 or (w['config'] & 8 == 0 and w['rren'] != 0
                    and w['crv'] + 1 <= 60 * 32768), 'Unsupported active watchdog observation')
        protocol['id'] = 'jlink-raw-swd-ap0-halted-backup-v1'
        scope.update(haltAttempted=True, memoryWrite=True, flashWrite=False, uicrWrite=False,
                     resetAttempted=a['method'] == 'reset-vector-catch')
    literal_record(manifest['protocol'], protocol, 'protocol')
    literal_record(manifest['scope'], scope, 'acquisition scope')
    validate_provenance(manifest['provenance'])
    try:
        require(bool(entries['README.txt'].decode('utf-8').strip()), 'Empty README')
    except UnicodeError as error:
        raise ValueError('README is not UTF-8') from error
    rows = manifest['regions']
    require(type(rows) is list and len(rows) == len(REGIONS), 'Incomplete region inventory')
    checked = {}
    for row, (name, start, size) in zip(rows, REGIONS):
        record(row, ('file', 'start', 'size', 'sha256', 'verifiedCopies'), 'region')
        require(row['file'] == name and row['start'] == f'0x{start:08x}'
                and type(row['size']) is int and row['size'] == size and len(entries[name]) == size
                and type(row['verifiedCopies']) is int and row['verifiedCopies'] == 2,
                'Invalid region order, extent or double-read claim: ' + name)
        require(type(row['sha256']) is str and SHA256.fullmatch(row['sha256']) is not None
                and sha(entries[name]) == row['sha256'], 'Region SHA256 mismatch: ' + name)
        checked[name] = dict(start=f'0x{start:08x}', size=size, sha256=sha(entries[name]))
    ficr = entries['ficr.bin']; flash = entries['flash.bin']
    def word(data, offset):
        return struct.unpack_from('<I', data, offset)[0]
    uid = [word(ficr, 0x60), word(ficr, 0x64)]
    require(all(word(ficr, offset) == value for offset, value in
                [(0x10, 4096), (0x14, 256), (0x100, 0x52840), (0x10c, 256), (0x110, 1024)]),
            'FICR PART or nRF52840 geometry mismatch')
    stack, reset = word(flash, 0), word(flash, 4)
    require(0x20000000 < stack <= 0x20040000 and stack % 8 == 0 and reset & 1
            and 8 <= (reset & ~1) < 0x100000, 'FLASH initial vectors are not plausible')
    recognized = [dict(row) for row in STOCK_APPLICATIONS
                  if sha(flash[row['offset']:row['offset'] + row['size']]) == row['sha256']]
    expected_target = dict(chip='nRF52840', part='0x00052840', uid=[f'0x{value:08x}' for value in uid],
                           identitySource='live FICR before/after both passes', commercialModelVerified=False,
                           model='stock application recognized; hardware model unverified' if recognized else 'unknown nRF52840 device')
    if recognized:
        expected_target.update(applicationDigestMatched=True, firmwareModel=','.join(dict.fromkeys(row['model'] for row in recognized)),
                               recognizedApplications=recognized)
    # All recognition is derived above from bytes, never from a model label.
    target = manifest['target']; record(target, expected_target, 'target')
    require(type(target['uid']) is list and len(target['uid']) == 2
            and all(type(value) is str and WORD_HEX.fullmatch(value) is not None for value in target['uid']), 'Malformed target UID')
    require(target['commercialModelVerified'] is False and target == expected_target,
            'Target identity or stock application recognition differs from exported bytes')
    if recognized:
        require(target['applicationDigestMatched'] is True, 'Invalid application digest-match claim')
        for row, expected in zip(target['recognizedApplications'], recognized):
            literal_record(row, expected, 'recognized application')
    result = dict(verified=True, archiveSha256=digest, chip='nRF52840', uid=[f'{value:08x}' for value in uid],
                  regions=checked, recognizedApplications=recognized, commercialModelVerified=False,
                  independentlyChecked=['bounded ZIP and strict manifest', 'all region hashes and sizes',
                                        'FICR UID/PART and geometry', 'plausible FLASH vectors', 'stock application slice hashes'],
                  producerReported=dict(byteExactDoubleRead=True, verifiedCopies=2,
                                        liveIdentitySource=target['identitySource'], protocol=protocol, scope=scope),
                  doubleAcquisitionIndependentlyProven=False, snapshotAtomic=False, restorationQualified=False,
                  limitations=['Single exported copy cannot prove independent acquisition passes, live reads or absence of target writes.',
                               'Matching repeat reads do not establish an atomic running-target snapshot.',
                               'This verification neither proves BLE restoration nor qualifies physical hardware.'])
    if halted:
        result['producerReported']['acquisition'] = dict(manifest['acquisition'])
        result['limitations'].append('CPU halt, exclusive ownership and reset-vector-catch provenance are producer-reported, not proven by this ZIP.')
    if compare_stock_recovery is not None:
        prior, prior_digest = read_archive(compare_stock_recovery, prior=True)
        for name, _, size in REGIONS:
            require(len(prior['stock-' + name]) == size and prior['stock-' + name] == entries[name],
                    'Prior stock recovery ' + name + ' differs from Android backup')
        result['comparison'] = dict(archiveSha256=prior_digest, allThreeRegionsByteIdentical=True,
                                    restorationPackageVerified=False,
                                    scope='Only FLASH/FICR/UICR dump bytes compared; restore artifacts and authorization not evaluated')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', type=Path, required=True, help='Exported Android five-entry ZIP (read only)')
    parser.add_argument('--compare-stock-recovery', type=Path,
                        help='Optional prior ZIP with root stock-flash.bin, stock-ficr.bin and stock-uicr.bin; dumps only')
    args = parser.parse_args(argv)
    try:
        result = verify_backup(args.backup, args.compare_stock_recovery)
    except (ValueError, OSError) as error:
        print('Backup verification failed: ' + str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
