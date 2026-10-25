#!/usr/bin/env python3
"""Build a device-bound ordinary signed recovery-migration primary; no hardware IO.

--manifest schema1 pins uid (two hexadecimal words), loader_path,
loader_sha256 (actual complete raw FLASH0..0xc000), restore_manifest_path,
restore_manifest_sha256, stock_restore_digest (authorized restorer.signed.bin
SHA256), and recovery_sha256. Paths resolve relative to the manifest. The
restoration authorization is an existing device's artifact-manifest.json with
matching deviceid and hashes of loader.hex/restorer.signed.bin. --recovery must
be the frozen ordinary signed0.7.1+0 recovery image, with recovery_version
explicitly pinned to 0.7.1+0 (earlier0.7.0 imports are unsupported). Outputs never include keys.

--prepare-only validates and freezes generated headers without invoking west.
Default builds a signed ordinary0.8.0+0 primary for the existing0xc000 slot.
This only prepares artifacts; it neither installs nor qualifies migration.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.firmware.package_zigbee_ota import image, run_imgtool, version_tuple
from tools.firmware.validate_recovery import read_hex, read_config, validate_uicr_preservation

from tools.firmware.toolchain_paths import toolchain_paths
_TOOLCHAIN = toolchain_paths()
SDK = _TOOLCHAIN['sdk']
WEST = _TOOLCHAIN['west']
PRIVATE_KEY = _TOOLCHAIN['private_key']
PUBLIC_KEY = _TOOLCHAIN['public_key']
LOADER_END = 0xc000
RECOVERY_START = 0xb0000
RECOVERY_CAPACITY = 0x40000
PRIMARY_CAPACITY = 0xa4000


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(value, name):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError(name + ' must be lowercase SHA256')
    return value


def uid_words(values):
    if not isinstance(values, list) or len(values) != 2:
        raise ValueError('UID must contain two words')
    result = []
    for value in values:
        if isinstance(value, str) and re.fullmatch('[0-9a-fA-F]{8}', value):
            result.append(int(value, 16))
        elif type(value) is int and 0 <= value <= 0xffffffff:
            result.append(value)
        else:
            raise ValueError('invalid UID word')
    return result


def check_slot(data, base, capacity, version=None):
    parsed = image(data)
    if (parsed['flags'] or len(data) > capacity or parsed['size'] < 8 or
            (version is not None and version_tuple(parsed['version']) != version_tuple(version))):
        raise ValueError('unsupported signed image version, size or flags')
    stack, reset = struct.unpack_from('<II', data, parsed['header'])
    if not 0x20000000 < stack <= 0x20040000 or stack % 8:
        raise ValueError('invalid image stack pointer')
    if not reset & 1 or not base + parsed['header'] <= (reset & ~1) < base + parsed['header'] + parsed['size']:
        raise ValueError('image reset vector outside permitted slot')
    return parsed


def validate_manifest(manifest_path, recovery_path):
    manifest_path, recovery_path = Path(manifest_path).resolve(), Path(recovery_path).resolve()
    data = json.loads(manifest_path.read_text())
    if type(data.get('schema_version')) is not int or data['schema_version'] not in (1,2):
        raise ValueError('unsupported migration manifest schema')
    uid = uid_words(data.get('uid'))
    profile=2 if data['schema_version']==2 else 1
    expected_version='0.7.3+0' if profile==2 else '0.7.1+0'
    if data.get('recovery_version')!=expected_version or (profile==2 and data.get('ota_profile')!=2):
        raise ValueError('recovery_version/profile must pin the supported recovery pair')
    for field in ('loader_sha256', 'restore_manifest_sha256', 'stock_restore_digest', 'recovery_sha256'):
        digest(data.get(field), field)
    def source(field):
        if not isinstance(data.get(field), str):
            raise ValueError('missing path: ' + field)
        return (manifest_path.parent / data[field]).resolve()
    authorization_path = source('restore_manifest_path')
    authorization_bytes = authorization_path.read_bytes()
    if sha(authorization_bytes) != data['restore_manifest_sha256']:
        raise ValueError('restoration authorization manifest SHA256 mismatch')
    authorization = json.loads(authorization_bytes)
    if uid_words(authorization.get('deviceid')) != uid:
        raise ValueError('restoration authorization belongs to another UID')
    loader_path = source('loader_path')
    loader_bytes = loader_path.read_bytes()
    loader_hex_path = authorization_path.parent / 'loader.hex'
    loader_hex = loader_hex_path.read_bytes()
    restorer_path = authorization_path.parent / 'restorer.signed.bin'
    restorer = restorer_path.read_bytes()
    for name, blob in (('loader.hex', loader_hex), ('restorer.signed.bin', restorer)):
        record = authorization.get('artifacts', {}).get(name, {})
        if record.get('size') != len(blob) or record.get('sha256') != sha(blob):
            raise ValueError('authorized restoration artifact mismatch: ' + name)
    if sha(restorer) != data['stock_restore_digest']:
        raise ValueError('stock restorer authorization digest mismatch')
    mapped = read_hex(loader_hex_path)
    if not mapped or min(mapped) < 0 or max(mapped) >= LOADER_END:
        raise ValueError('authorized loader crosses FLASH0..0xc000')
    if len(loader_bytes) != LOADER_END:
        raise ValueError('current loader raw snapshot must cover exactly FLASH0..0xc000')
    if sha(loader_bytes) != data['loader_sha256']:
        raise ValueError('current loader raw FLASH SHA256 mismatch')
    if any(loader_bytes[address] != value for address, value in mapped.items()):
        raise ValueError('current loader bytes differ from authorized loader HEX')
    snapshot_source = {}
    if any(field in data for field in ('source_snapshot', 'source_snapshot_sha256', 'transformation')):
        snapshot_path = source('source_snapshot')
        snapshot_bytes = snapshot_path.read_bytes()
        expected_snapshot = digest(data.get('source_snapshot_sha256'), 'source_snapshot_sha256')
        if (sha(snapshot_bytes) != expected_snapshot or
                data.get('transformation') != 'first0xc000bytesverbatim' or
                snapshot_bytes[:LOADER_END] != loader_bytes):
            raise ValueError('source snapshot does not reproduce actual loader bytes')
        snapshot_source = {'source_snapshot': dict(path=str(snapshot_path), sha256=expected_snapshot)}
    recovery = recovery_path.read_bytes()
    if sha(recovery) != data['recovery_sha256']:
        raise ValueError('replacement recovery SHA256 mismatch')
    check_slot(recovery, RECOVERY_START, 0x34000 if profile==2 else RECOVERY_CAPACITY, data['recovery_version'])
    pair_sources={}
    if profile==2:
        def pinned(name):
            entry=data.get(name)
            if not isinstance(entry,dict) or not isinstance(entry.get('path'),str):raise ValueError('missing '+name)
            path=(manifest_path.parent/entry['path']).resolve();blob=path.read_bytes()
            if sha(blob)!=digest(entry.get('sha256'),name):raise ValueError(name+' SHA256 mismatch')
            pair_sources[name]=dict(path=str(path),sha256=sha(blob));return path,blob
        pair_path,pair_blob=pinned('pair_bindings');config_path,config_blob=pinned('recovery_config')
        pair=json.loads(pair_blob);config=read_config(config_path)
        if (pair.get('schema_version')!=1 or pair.get('ota_profile')!=2 or pair.get('recovery_sha256')!=sha(recovery) or
            data['loader_sha256'] not in pair.get('allowed_loaders',[]) or pair.get('recovery_config_sha256')!=sha(config_blob)):
            raise ValueError('recovery/loader pair authorization mismatch')
        if any(config.get(k)!='y' for k in ['CONFIG_VIMAR_OTA_SPLIT_STAGING','CONFIG_VIMAR_P031_PROTECTION','CONFIG_VIMAR_OTA_INSTALLER']) or config.get('CONFIG_NRF_COMPRESS_LZMA_MAX_DICT_SIZE')!='32768' or config.get('CONFIG_DISABLE_FLASH_PATCH')=='y':
            raise ValueError('incompatible native recovery configuration')
    check_slot(restorer, RECOVERY_START, RECOVERY_CAPACITY)
    commands = []
    # Snapshot verification avoids validating different bytes if a build artifact
    # changes between the hash read and signature verifier opening the path.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='vimar-migration-verify-') as temporary:
        for name, blob in (('recovery', recovery), ('restorer', restorer)):
            frozen = Path(temporary) / (name + '.bin')
            frozen.write_bytes(blob)
            run_imgtool(['verify', '-k', PUBLIC_KEY, frozen], commands)
    return dict(uid=uid, ota_profile=profile, loader_sha256=data['loader_sha256'],
                stock_restore_digest=data['stock_restore_digest'], recovery_sha256=sha(recovery),
                recovery_version=data['recovery_version'],
                recovery_bytes=recovery, sources={
                    'input_manifest': dict(path=str(manifest_path), sha256=sha(manifest_path.read_bytes())),
                    'restore_manifest': dict(path=str(authorization_path), sha256=sha(authorization_bytes)),
                    'loader_raw': dict(path=str(loader_path), sha256=sha(loader_bytes)),
                    'loader_hex': dict(path=str(loader_hex_path), sha256=sha(loader_hex)),
                    'restorer': dict(path=str(restorer_path), sha256=sha(restorer)),
                    'recovery': dict(path=str(recovery_path), sha256=sha(recovery)),
                    **snapshot_source,**pair_sources}, commands=commands)


def c_digest(name, value):
    return f'static const uint8_t {name}[32] = {{' + ','.join(f'0x{x:02x}' for x in bytes.fromhex(value)) + '};\n'


def prepare_migration(manifest_path, recovery_path, output_dir):
    output = Path(output_dir).resolve()
    if output.is_relative_to(ROOT / 'inputs'):
        raise ValueError('cannot write immutable inputs')
    if output.exists() and any(output.iterdir()):
        raise ValueError('migration output must be empty')
    validated = validate_manifest(manifest_path, recovery_path)
    recovery = validated.pop('recovery_bytes')
    generated = output / 'generated'
    generated.mkdir(parents=True)
    header = '#ifndef VIMAR_MIGRATION_TARGET_UID_H\n#define VIMAR_MIGRATION_TARGET_UID_H\n#include <stdint.h>\n'
    header += ''.join(f'#define MIGRATION_UID{i} 0x{word:08x}u\n' for i, word in enumerate(validated['uid']))
    for name, value in [('expected_loader_sha256', validated['loader_sha256']),
                        ('expected_restorer_sha256', validated['stock_restore_digest']),
                        ('expected_recovery_sha256', validated['recovery_sha256'])]:
        header += c_digest(name, value)
    (generated / 'target_uid.h').write_text(header + '#endif\n')
    body = '\n'.join(','.join(f'0x{x:02x}' for x in recovery[offset:offset+16])+','
                     for offset in range(0, len(recovery), 16))
    (generated / 'recovery_blob.h').write_text('#ifndef VIMAR_MIGRATION_RECOVERY_BLOB_H\n#define VIMAR_MIGRATION_RECOVERY_BLOB_H\n#include <stdint.h>\n'
        + f'#define RECOVERY_BLOB_SIZE {len(recovery)}u\n'
        + 'static const uint8_t recovery_blob[] __attribute__((aligned(4))) = {\n' + body + '\n};\n#endif\n')
    (output / ('recovery-' + validated['recovery_version'].split('+')[0] + '.signed.bin')).write_bytes(recovery)
    report = dict(validated, schema_version=1, migration_version='0.8.1+0' if validated['ota_profile']==2 else '0.8.0+0',
                  builder_sha256=sha(Path(__file__).read_bytes()),
                  status='prepared only; no bootstrap build or hardware qualification',
                  hardware_qualified=False, generated_dir=str(generated),
                  transformations=['exact signed recovery bytes to aligned constant C array',
                                   'exact UID and actual raw loader/restorer/recovery SHA256 to C constants'],
                  generated_sha256={path.name: sha(path.read_bytes()) for path in generated.iterdir()})
    manifest_out = output / 'migration-manifest.json'
    manifest_out.write_text(json.dumps(report, indent=2)+'\n')
    return dict(output_dir=str(output), generated_dir=str(generated), manifest_path=str(manifest_out))


def validate_split_migration_config(config):
    for key in ['CONFIG_SETTINGS_NVS','CONFIG_NVS','CONFIG_SETTINGS','CONFIG_VIMAR_P031_PROTECTION','CONFIG_VIMAR_OTA_SPLIT_STAGING','CONFIG_SOC_FLASH_NRF_PARTIAL_ERASE']:
        if config.get(key)!='y':raise ValueError('split migration requires effective '+key+'=y')


def build_migration(manifest_path, recovery_path, output_dir):
    result = prepare_migration(manifest_path, recovery_path, output_dir)
    output = Path(result['output_dir'])
    build = output / 'build'
    command = [str(WEST), 'build', '--pristine', '--no-sysbuild', '-b', 'nrf52840dk/nrf52840',
               str(ROOT / 'firmware/ota_migration'), '-d', str(build), '--',
               '-DGENERATED_DIR=' + result['generated_dir'],
               '-DDTC_OVERLAY_FILE=' + ';'.join(map(str, [ROOT / 'firmware/boards/nrf52840dk_nrf52840_ota.overlay', ROOT / 'firmware/research/vimar-candidate.overlay'])),
               '-DEXTRA_CONF_FILE=' + str(ROOT / 'firmware/research/vimar-candidate.conf'),
               '-DCONFIG_MCUBOOT_SIGNATURE_KEY_FILE="' + str(PRIVATE_KEY) + '"',
               '-DCONFIG_MCUBOOT_IMGTOOL_SIGN_VERSION="0.8.0+0"']
    report_path = Path(result['manifest_path'])
    report = json.loads(report_path.read_text())
    if report.get('ota_profile')==2:
        command=[arg.replace('0.8.0+0','0.8.1+0') for arg in command]
        command+=['-DCONFIG_VIMAR_P031_PROTECTION=y','-DCONFIG_VIMAR_OTA_SPLIT_STAGING=y','-DCONFIG_SETTINGS=y','-DCONFIG_NVS=y','-DCONFIG_SETTINGS_NVS=y','-DCONFIG_SOC_FLASH_NRF_PARTIAL_ERASE_MS=6']
    report['commands'].append(command)
    report['build_cwd'] = str(SDK)
    report['application_sources'] = {str(path.relative_to(ROOT)): sha(path.read_bytes())
        for path in sorted((ROOT / 'firmware/ota_migration').rglob('*')) if path.is_file()}
    report['status'] = 'build started; not installable until validation completes'
    report_path.write_text(json.dumps(report, indent=2)+'\n')
    print('Building device-bound migration; log: ' + str(output / 'build.log'), flush=True)
    with (output / 'build.log').open('w') as log:
        subprocess.run(command, cwd=SDK, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=900)
    signed_path = build / 'zephyr/zephyr.signed.bin'
    signed = signed_path.read_bytes()
    check_slot(signed, 0xc000, PRIMARY_CAPACITY, report['migration_version'])
    run_imgtool(['verify', '-k', PUBLIC_KEY, signed_path], report['commands'])
    config = read_config(build / 'zephyr/.config')
    if report.get('ota_profile')==2:validate_split_migration_config(config)
    defines = set(re.findall(r'-D([A-Za-z0-9_]+)', (build / 'build.ninja').read_text()))
    validate_uicr_preservation({'migration': config}, {'migration': defines})
    if config.get('CONFIG_NORDIC_QSPI_NOR') == 'y' or config.get('CONFIG_BT') == 'y':
        raise ValueError('unexpected QSPI/BLE transport in migration image')
    mapped = read_hex(build / 'zephyr/zephyr.signed.hex')
    if not mapped or min(mapped) != 0xc000 or max(mapped) >= 0xb0000:
        raise ValueError('migration signed HEX outside primary interval')
    run_imgtool(['verify', '-k', PUBLIC_KEY, build / 'zephyr/zephyr.signed.hex'], report['commands'])
    stem='migration-'+report['migration_version'].split('+')[0]
    for suffix in ('bin', 'hex'):
        destination = output / (stem+'.signed.'+suffix)
        shutil.copyfile(build / ('zephyr/zephyr.signed.' + suffix), destination)
        report.setdefault('artifacts', {})[destination.name] = dict(size=destination.stat().st_size, sha256=sha(destination.read_bytes()))
    report['status'] = 'signed ordinary bootstrap verified; hardware qualification pending'
    report_path.write_text(json.dumps(report, indent=2)+'\n')
    result['image_path'] = str(output / (stem+'.signed.bin'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--recovery', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    operation = prepare_migration if args.prepare_only else build_migration
    print(json.dumps(operation(args.manifest, args.recovery, args.output), indent=2))


if __name__ == '__main__':
    main()
