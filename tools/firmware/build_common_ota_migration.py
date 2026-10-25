#!/usr/bin/env python3
"""Prepare/build an UNSIGNED common recovery-migration primary; no hardware IO.

Schema1 kind common-recovery-migration pins model VIMAR30805, ota_profile2,
recovery_signed, recovery_config, audited_loader_config and
loader_compatibility_registry as {path,sha256}; allowed_loaders is a list of
1..64 exact raw FLASH0..0xc000 source records. Paths resolve from the manifest.
The pinned registry uses the pair_bindings schema1/profile2 allowed_loaders and
reference_loader_config_sha256 fields. It is explicit finite release authority,
not evidence that arbitrary future loaders are compatible.

--prepare-only freezes headers and provenance using only a public verification
key. Default builds an unsigned ELF/bin; it never signs and is not installable.
A separately authorized release signing step must add protected MIGRATION role3
and VIMAR30805/profile2 metadata. No UID or restorer inputs are accepted.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.firmware.build_ota_migration import check_slot, c_digest, validate_split_migration_config
from tools.firmware.package_zigbee_ota import run_imgtool
from tools.firmware.toolchain_paths import toolchain_paths
from tools.firmware.validate_recovery import read_config, read_hex, validate_uicr_preservation

_PATHS = toolchain_paths()
PUBLIC_KEY = _PATHS['public_key']
SDK, WEST = _PATHS['sdk'], _PATHS['west']
LOADER_SIZE, RECOVERY_LIMIT = 0xc000, 0x34000


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('expected lowercase SHA256')
    return value


def config_values(data):
    return dict(line.split('=', 1) for line in data.decode().splitlines()
                if line.startswith('CONFIG_') and '=' in line)


def validate_common_manifest(manifest_path):
    path = Path(manifest_path).resolve()
    manifest_bytes = path.read_bytes()
    manifest = json.loads(manifest_bytes)
    expected = dict(schema_version=1, kind='common-recovery-migration', model='VIMAR30805', ota_profile=2)
    required = set(expected) | {'recovery_signed', 'recovery_config', 'audited_loader_config',
                                'loader_compatibility_registry', 'allowed_loaders'}
    if (not isinstance(manifest, dict) or set(manifest) != required or
            any(type(manifest.get(k)) is not type(v) or manifest[k] != v for k, v in expected.items())):
        raise ValueError('unsupported common migration manifest; per-unit fields are not accepted')
    sources = {'input_manifest': dict(path=str(path), sha256=sha(manifest_bytes))}

    def record(name, entry):
        if not isinstance(entry, dict) or set(entry) != {'path', 'sha256'} or not isinstance(entry['path'], str):
            raise ValueError('invalid source record: '+name)
        source = (path.parent / entry['path']).resolve()
        data = source.read_bytes()
        if sha(data) != digest(entry['sha256']):
            raise ValueError('source SHA256 mismatch: '+name)
        sources[name] = dict(path=str(source), sha256=sha(data), size=len(data))
        return data

    loader_config_data = record('audited_loader_config', manifest['audited_loader_config'])
    config = config_values(loader_config_data)
    for key in ('CONFIG_BOOT_FIRMWARE_LOADER', 'CONFIG_BOOT_VALIDATE_SLOT0', 'CONFIG_BOOT_SIGNATURE_TYPE_ECDSA_P256'):
        if config.get(key) != 'y':
            raise ValueError('unsupported audited loader configuration: '+key)
    for key in ('CONFIG_BOOT_SWAP_USING_SCRATCH', 'CONFIG_BOOT_SWAP_USING_OFFSET',
                'CONFIG_BOOT_SWAP_USING_MOVE', 'CONFIG_BOOT_ENCRYPT_IMAGE', 'CONFIG_DISABLE_FLASH_PATCH'):
        if config.get(key) == 'y':
            raise ValueError('unsupported loader swap/encryption/UICR configuration')
    registry = json.loads(record('loader_compatibility_registry', manifest['loader_compatibility_registry']))
    registered = registry.get('allowed_loaders') if isinstance(registry, dict) else None
    if (not isinstance(registry, dict) or type(registry.get('schema_version')) is not int or registry['schema_version'] != 1 or
            type(registry.get('ota_profile')) is not int or registry['ota_profile'] != 2 or
            registry.get('reference_loader_config_sha256') != sha(loader_config_data) or
            not isinstance(registered, list) or not 1 <= len(registered) <= 64):
        raise ValueError('incompatible loader registry/config provenance')
    registered = {digest(value) for value in registered}
    entries = manifest['allowed_loaders']
    if not isinstance(entries, list) or not 1 <= len(entries) <= 64:
        raise ValueError('common loader allowlist must contain 1..64 entries')
    allowed = []
    for index, entry in enumerate(entries):
        data = record('loader_raw_'+str(index), entry)
        if len(data) != LOADER_SIZE or sha(data) not in registered:
            raise ValueError('unknown loader or raw snapshot not exactly FLASH0..0xc000')
        if sha(data) in allowed:
            raise ValueError('duplicate loader authorization')
        allowed.append(sha(data))
    recovery = record('recovery_signed', manifest['recovery_signed'])
    parsed = check_slot(recovery, 0xb0000, RECOVERY_LIMIT)
    if parsed['protected'].get(0xa0) != b'VIMAR30805\x02' or parsed['protected'].get(0xa1) != b'\x02':
        raise ValueError('replacement recovery requires protected RECOVERY role and exact profile2')
    if registry.get('recovery_sha256') not in (None, sha(recovery)):
        raise ValueError('registry recovery binding differs from replacement recovery')
    recovery_config = config_values(record('recovery_config', manifest['recovery_config']))
    if registry.get('recovery_config_sha256') not in (None, sources['recovery_config']['sha256']):
        raise ValueError('registry recovery configuration binding differs')
    if (any(recovery_config.get(key) != 'y' for key in ('CONFIG_VIMAR_OTA_SPLIT_STAGING',
            'CONFIG_VIMAR_P031_PROTECTION', 'CONFIG_VIMAR_OTA_INSTALLER')) or
            recovery_config.get('CONFIG_NRF_COMPRESS_LZMA_MAX_DICT_SIZE') != '32768' or
            recovery_config.get('CONFIG_DISABLE_FLASH_PATCH') == 'y'):
        raise ValueError('replacement recovery configuration is incompatible')
    commands = []
    public_bytes = PUBLIC_KEY.read_bytes()
    sources['verification_public_key'] = dict(path=str(PUBLIC_KEY), sha256=sha(public_bytes), size=len(public_bytes))
    # Verify exactly the already-pinned bytes, never a subsequently changed path.
    with tempfile.TemporaryDirectory(prefix='vimar-common-migration-verify-') as temporary:
        frozen = Path(temporary) / 'recovery.bin'
        public_frozen = Path(temporary) / 'verification-public.pem'
        frozen.write_bytes(recovery)
        public_frozen.write_bytes(public_bytes)
        run_imgtool(['verify', '-k', public_frozen, frozen], commands)
    return dict(recovery_bytes=recovery, recovery_sha256=sha(recovery),
                recovery_version=parsed['version'], recovery_role='recovery', ota_profile=2,
                allowed_loaders=sorted(allowed), sources=sources, commands=commands)


def prepare_common_migration(manifest_path, output_dir):
    output = Path(output_dir).resolve()
    if output.is_relative_to(ROOT/'inputs'):
        raise ValueError('cannot write immutable inputs')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('common migration output must be empty')
    validated = validate_common_manifest(manifest_path)
    recovery = validated.pop('recovery_bytes')
    generated = output/'generated'
    generated.mkdir(parents=True)
    header = '#ifndef VIMAR_MIGRATION_COMMON_PLATFORM_H\n#define VIMAR_MIGRATION_COMMON_PLATFORM_H\n#include <stdint.h>\n'
    header += '#define MIGRATION_ALLOWED_LOADER_COUNT '+str(len(validated['allowed_loaders']))+'u\n'
    header += 'static const uint8_t migration_allowed_loaders[][32] = {\n'
    for value in validated['allowed_loaders']:
        header += '{'+','.join('0x'+value[index:index+2] for index in range(0, 64, 2))+'},\n'
    header += '};\n'+c_digest('expected_recovery_sha256', validated['recovery_sha256'])+'#endif\n'
    (generated/'common_platform.h').write_text(header)
    body = '\n'.join(','.join(f'0x{x:02x}' for x in recovery[offset:offset+16])+','
                     for offset in range(0, len(recovery), 16))
    (generated/'recovery_blob.h').write_text('#ifndef VIMAR_MIGRATION_RECOVERY_BLOB_H\n#define VIMAR_MIGRATION_RECOVERY_BLOB_H\n#include <stdint.h>\n'
        +f'#define RECOVERY_BLOB_SIZE {len(recovery)}u\n'
        +'static const uint8_t recovery_blob[] __attribute__((aligned(4))) = {\n'+body+'\n};\n#endif\n')
    (output/'recovery.signed.bin').write_bytes(recovery)
    report = dict(validated, schema_version=1, kind='common-recovery-migration',
        builder_sha256=sha(Path(__file__).read_bytes()), generated_dir=str(generated),
        status='prepared only; unsigned bootstrap not built', hardware_qualified=False,
        compatibility='finite exact loader allowlist only; unknown legacy/future loaders rejected',
        loader_config_provenance_requires_qualification=True, recovery_config_provenance_requires_qualification=True,
        transformations=['exact signed recovery bytes to aligned immutable C array',
                         'sorted finite authorized raw loader hashes and recovery SHA256 to C constants; no UID/restorer'],
        required_signing_metadata=dict(role='migration', role_tlv=0xa1, role_value=3, target_tlv=0xa0, profile=2),
        generated_sha256={p.name: sha(p.read_bytes()) for p in generated.iterdir()})
    manifest_out = output/'common-migration-manifest.json'
    manifest_out.write_text(json.dumps(report, indent=2)+'\n')
    return dict(output_dir=str(output), generated_dir=str(generated), manifest_path=str(manifest_out))


def unsigned_build_command(result):
    return [str(WEST), 'build', '--pristine', '--no-sysbuild', '-b', 'nrf52840dk/nrf52840',
        str(ROOT/'firmware/ota_migration'), '-d', str(Path(result['output_dir'])/'build'),
        '--target', 'zephyr/zephyr.elf', '--', '-DGENERATED_DIR='+result['generated_dir'],
        '-DDTC_OVERLAY_FILE='+';'.join(map(str, [ROOT/'firmware/boards/nrf52840dk_nrf52840_ota.overlay',
                                                ROOT/'firmware/research/vimar-candidate.overlay'])),
        '-DEXTRA_CONF_FILE='+str(ROOT/'firmware/research/vimar-candidate.conf'),
        '-DCONFIG_MIGRATION_COMMON=y', '-DCONFIG_VIMAR_OTA_SPLIT_STAGING=y',
        '-DCONFIG_VIMAR_P031_PROTECTION=y', '-DCONFIG_SETTINGS=y', '-DCONFIG_NVS=y',
        '-DCONFIG_SETTINGS_NVS=y', '-DCONFIG_SOC_FLASH_NRF_PARTIAL_ERASE_MS=6',
        '-DCONFIG_MCUBOOT_GENERATE_UNSIGNED_IMAGE=n', '-DCONFIG_MCUBOOT_SIGNATURE_KEY_FILE=""']


def build_unsigned_migration(manifest_path, output_dir):
    result = prepare_common_migration(manifest_path, output_dir)
    output = Path(result['output_dir'])
    report_path = Path(result['manifest_path'])
    report = json.loads(report_path.read_text())
    command = unsigned_build_command(result)
    report['commands'].append(command)
    report['application_sources'] = {str(p.relative_to(ROOT)): sha(p.read_bytes())
        for p in sorted((ROOT/'firmware/ota_migration').rglob('*')) if p.is_file()}
    for relative in ('firmware/ota/ota_image.c', 'firmware/ota/ota_image.h', 'firmware/ota/ota_reader.h',
                     'firmware/src/vimar_power_protection.c', 'firmware/src/candidate_power_protection.c',
                     'firmware/research/src/research_handoff.c'):
        report['application_sources'][relative] = sha((ROOT/relative).read_bytes())
    report['status'] = 'unsigned build started; not installable'
    report_path.write_text(json.dumps(report, indent=2)+'\n')
    with (output/'build.log').open('w') as log:
        subprocess.run(command, cwd=SDK, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=900)
    build = output/'build'
    config = read_config(build/'zephyr/.config')
    validate_split_migration_config(config)
    if config.get('CONFIG_MIGRATION_COMMON') != 'y' or config.get('CONFIG_MCUBOOT_SIGNATURE_KEY_FILE') != '""':
        raise ValueError('effective build is not common/unsigned')
    if any(config.get(k) == 'y' for k in ('CONFIG_BT', 'CONFIG_NORDIC_QSPI_NOR', 'CONFIG_MIGRATION_STAGE_PROBE')):
        raise ValueError('unexpected BLE/QSPI/stage probe in common migration')
    defines = set(re.findall(r'-D([A-Za-z0-9_]+)', (build/'build.ninja').read_text()))
    validate_uicr_preservation({'common_migration': config}, {'common_migration': defines})
    report['effective_config_sha256'] = sha((build/'zephyr/.config').read_bytes())
    mapped = read_hex(build/'zephyr/zephyr.hex')
    if not mapped or min(mapped) != 0xc000 or max(mapped) >= 0xb0000:
        raise ValueError('unsigned common image exceeds primary flash authority')
    report['artifacts'] = {}
    for suffix in ('elf', 'bin', 'hex'):
        source = build/('zephyr/zephyr.'+suffix)
        destination = output/('migration.common.unsigned.'+suffix)
        shutil.copyfile(source, destination)
        report['artifacts'][destination.name] = dict(size=destination.stat().st_size, sha256=sha(destination.read_bytes()))
    report['status'] = 'unsigned common bootstrap built and bounds checked; signing and hardware qualification pending'
    report_path.write_text(json.dumps(report, indent=2)+'\n')
    result['unsigned_image_path'] = str(output/'migration.common.unsigned.bin')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    operation = prepare_common_migration if args.prepare_only else build_unsigned_migration
    print(json.dumps(operation(args.manifest, args.output), indent=2))


if __name__ == '__main__':
    main()
