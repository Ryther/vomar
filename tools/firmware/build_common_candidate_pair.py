#!/usr/bin/env python3
"""Build/sign a local common candidate pair and bootstrap, never program hardware.

Explicit authorization input is the existing loader-authorizations bindings
manifest; all device-specific authorization records remain private provenance.
Only finite loader hashes enter generated common headers. Candidate artifacts
are unqualified and cannot be passed as release qualification evidence.
"""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.firmware import build_common_ota_migration as common
from tools.firmware.build_ota_pair_bindings import prepare_pair_bindings
from tools.firmware.build_ota_migration import check_slot
from tools.firmware.package_zigbee_ota import image, package_release
from tools.firmware.toolchain_paths import toolchain_paths
from tools.firmware.validate_recovery import read_config, read_hex, validate_uicr_preservation

VERSIONS = dict(main='0.6.0', recovery='0.8.0', migration='0.9.0')
ROLES = dict(main=1, recovery=2, migration=3)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def record(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=sha(path.read_bytes()))


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2) + '\n')
    return Path(path)


def version_file(path, version):
    major, minor, patch = version.split('.')
    Path(path).write_text(f'VERSION_MAJOR = {major}\nVERSION_MINOR = {minor}\nPATCHLEVEL = {patch}\nVERSION_TWEAK = 0\nEXTRAVERSION =\n')


def build_candidate(authorization_manifest, current_main, output):
    paths = toolchain_paths()
    output = Path(output).resolve()
    if output.is_relative_to(ROOT/'inputs') or (output.exists() and any(output.iterdir())):
        raise ValueError('candidate output must be new/empty and outside inputs')
    output.mkdir(parents=True, exist_ok=True)
    artifacts = output/'artifacts'
    artifacts.mkdir()
    report = dict(schema_version=1, kind='unqualified-common-candidate', model='VIMAR30805',
        ota_profile=2, versions=VERSIONS, status='build started', hardware_qualified=False,
        pending_checks=['native pair independent review', 'physical button/service/identity validation',
                        'physical common migration on compatible loaders', 'physical power-cut recovery',
                        'Android authenticated live identity and BLE transfer'],
        commands=[], sources=dict(loader_authorization_input=record(authorization_manifest),
                                 current_main=record(current_main)), artifacts={})
    report_path = output/'candidate-manifest.json'

    def save():
        write_json(report_path, report)

    def run(arguments, log_name, cwd=None):
        arguments = list(map(str, arguments))
        report['commands'].append(dict(argv=arguments, cwd=str(cwd or ROOT), log=log_name))
        save()
        with (output/log_name).open('w') as log:
            subprocess.run(arguments, cwd=cwd or ROOT, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=1200)

    # Exact source snapshot excludes all keys; source hashes and transformations
    # record the explicit candidate VERSION changes separately from workspace.
    source_root = output/'source'
    firmware = source_root/'firmware'
    shutil.copytree(ROOT/'firmware', firmware, ignore=shutil.ignore_patterns('keys', '__pycache__'))
    report['workspace_source_sha256'] = {str(p.relative_to(ROOT)): sha(p.read_bytes())
        for p in (ROOT/'firmware').rglob('*') if p.is_file() and 'keys' not in p.relative_to(ROOT/'firmware').parts}
    for name, path in [('main', firmware/'VERSION'), ('recovery', firmware/'recovery/VERSION'),
                       ('migration', firmware/'ota_migration/VERSION')]:
        version_file(path, VERSIONS[name])
    report['source_transformations'] = ['copy firmware tree excluding keys; no device backups',
        'set main/recovery/migration VERSION to explicit candidate SemVer triples']
    report['frozen_source_sha256'] = {str(p.relative_to(source_root)): sha(p.read_bytes())
        for p in firmware.rglob('*') if p.is_file()}
    save()

    # Validate actual private loader/restore authorization, then freeze a public
    # common header containing only authorized loader digests, no UID constants.
    recovered = prepare_pair_bindings(authorization_manifest, output/'private-authorization')
    registry = json.loads(Path(recovered['report_path']).read_text())
    report['allowed_loaders'] = registry['allowed_loaders']
    frozen_header = output/'recovery-pair-bindings.h'
    shutil.copyfile(recovered['header_path'], frozen_header)
    auth = json.loads(Path(authorization_manifest).read_text())
    auth_base = Path(authorization_manifest).resolve().parent
    loader_config = (auth_base/auth['audited_loader_config']['path']).resolve()
    service = output/'recovery-candidate.conf'
    service.write_text('CONFIG_MCUBOOT_SIGNATURE_KEY_FILE=""\nCONFIG_MCUBOOT_GENERATE_UNSIGNED_IMAGE=n\n'
        'CONFIG_BOOTLOADER_MCUBOOT=y\nCONFIG_MCUBOOT_BOOTLOADER_MODE_FIRMWARE_UPDATER=y\n'
        'CONFIG_VIMAR_P031_PROTECTION=y\nCONFIG_VIMAR_RECOVERY_BUTTON_EXIT=y\n'
        'CONFIG_VIMAR_RECOVERY_SERVICE_MODE=y\nCONFIG_VIMAR_RECOVERY_IDENTITY=y\n'
        'CONFIG_VIMAR_OTA_SPLIT_STAGING=y\nCONFIG_IMG_ENABLE_IMAGE_CHECK=n\n')
    unsigned = output/'unsigned.conf'
    unsigned.write_text('CONFIG_MCUBOOT_SIGNATURE_KEY_FILE=""\nCONFIG_MCUBOOT_GENERATE_UNSIGNED_IMAGE=n\n')
    target = output/'target-profile2.bin'
    target.write_bytes(b'VIMAR30805\x02')

    def native(name, source, conf, overlays, extras, binding):
        build = output/(name+'-build')
        run([paths['west'], 'build', '--pristine', '--no-sysbuild', '-b', 'nrf52840dk/nrf52840',
            source, '-d', build, '--target', 'zephyr/zephyr.elf', '--',
            '-DCONF_FILE='+str(conf), '-DDTC_OVERLAY_FILE='+';'.join(map(str, overlays)),
            '-DEXTRA_CONF_FILE='+';'.join(map(str, extras)),
            '-DVIMAR_OTA_PAIR_BINDINGS_HEADER='+str(binding)], name+'-build.log', paths['sdk'])
        config = read_config(build/'zephyr/.config')
        if any(config.get(k) != 'y' for k in ['CONFIG_VIMAR_P031_PROTECTION','CONFIG_VIMAR_OTA_SPLIT_STAGING']):
            raise ValueError(name+' missing protected split configuration')
        if config.get('CONFIG_MCUBOOT_SIGNATURE_KEY_FILE') != '""':
            raise ValueError('native builds must remain unsigned')
        if name == 'recovery':
            required = ['CONFIG_VIMAR_RECOVERY_SERVICE_MODE','CONFIG_VIMAR_RECOVERY_IDENTITY',
                        'CONFIG_VIMAR_RECOVERY_BUTTON_EXIT','CONFIG_VIMAR_OTA_INSTALLER',
                        'CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN','CONFIG_BT_SMP']
            if any(config.get(k) != 'y' for k in required) or config.get('CONFIG_IMG_ENABLE_IMAGE_CHECK') == 'y':
                raise ValueError('incomplete recovery service/identity/exit configuration')
        elif config.get('CONFIG_BT') == 'y' or config.get('CONFIG_VIMAR_ZIGBEE_OTA') != 'y':
            raise ValueError('main must use Zigbee with BLE isolated in recovery')
        defines = set(re.findall(r'-D([A-Za-z0-9_]+)', (build/'build.ninja').read_text()))
        validate_uicr_preservation({name:config},{name:defines})
        mapped = read_hex(build/'zephyr/zephyr.hex')
        base, end = (0xb0000,0xe4000) if name=='recovery' else (0xc000,0xae000)
        if not mapped or min(mapped) != base or max(mapped) >= end:
            raise ValueError(name+' unsigned HEX exceeds code bounds')
        for suffix in ['bin','elf','hex']:
            shutil.copyfile(build/('zephyr/zephyr.'+suffix),artifacts/(name+'.unsigned.'+suffix))
        shutil.copyfile(build/'zephyr/.config',artifacts/(name+'.config'))
        shutil.copyfile(build/'zephyr/zephyr.dts',artifacts/(name+'.dts'))
        return artifacts/(name+'.unsigned.bin')

    def sign(name, raw):
        role = output/('role-'+name+'.bin')
        role.write_bytes(bytes([ROLES[name]]))
        signed = artifacts/(name+'-'+VERSIONS[name]+'.signed.bin')
        run([paths['python'],paths['imgtool'],'sign','--header-size','512','--slot-size',
            '0x34000' if name=='recovery' else '0xa2000','--align','4','--overwrite-only',
            '--version',VERSIONS[name],'-k',paths['private_key'],'--custom-tlv-file','0xa0',target,
            '--custom-tlv-file','0xa1',role,raw,signed],name+'-sign.log')
        parsed = check_slot(signed.read_bytes(),0xb0000 if name=='recovery' else 0xc000,
                            0x34000 if name=='recovery' else 0xa2000,VERSIONS[name])
        if parsed['protected'].get(0xa0)!=b'VIMAR30805\x02' or parsed['protected'].get(0xa1)!=bytes([ROLES[name]]):
            raise ValueError('signer omitted required protected role/profile')
        run([paths['python'],paths['imgtool'],'verify','-k',paths['public_key'],signed],name+'-verify.log')
        report['artifacts'][name]=dict(record(signed),size=signed.stat().st_size,role=name,version=VERSIONS[name],
                                      signed_region_sha256=sha(signed.read_bytes()[:parsed['authenticated_end']]))
        save()
        return signed

    recovery_raw = native('recovery', firmware/'recovery',firmware/'recovery/prj.conf',
        [firmware/'boards/ota-loader.overlay',firmware/'research/vimar-candidate.overlay'],
        [firmware/'research/vimar-candidate.conf',firmware/'ota/crypto.conf',firmware/'ota/recovery.conf',service],frozen_header)
    recovery = sign('recovery', recovery_raw)
    report['recovery_code_margin'] = 0x34000-recovery.stat().st_size
    # Derive main binding only after the final signed recovery is immutable.
    bound_manifest = dict(auth,recovery_signed=record(recovery),recovery_config=record(artifacts/'recovery.config'),
                          recovery_version=VERSIONS['recovery'])
    # Existing source paths are absolute in the pinned authorization manifest.
    bound_path = write_json(output/'private-main-bindings-input.json',bound_manifest)
    bindings = prepare_pair_bindings(bound_path,output/'main-bindings')
    bindings_json = json.loads(Path(bindings['report_path']).read_text())
    # Common registry contains only compatibility hashes/config provenance.
    common_registry = {k:v for k,v in bindings_json.items() if k not in ['authorizations','commands']}
    registry_path = write_json(output/'common-loader-registry.json',common_registry)
    main_raw = native('main',firmware,firmware/'prj_split_ota.conf',
        [firmware/'boards/nrf52840dk_nrf52840_ota.overlay',firmware/'research/vimar-candidate.overlay'],
        [firmware/'vimar_zigbee.conf',firmware/'research/vimar-candidate.conf',firmware/'ota/crypto.conf',unsigned],
        Path(bindings['header_path']))
    main = sign('main',main_raw)

    allowed_raw=[]
    for entry in auth['loader_authorizations']:
        manifest_path=(auth_base/entry['manifest']['path']).resolve()
        unit=json.loads(manifest_path.read_text())
        allowed_raw.append(record((manifest_path.parent/unit['loader_path']).resolve()))
    migration_input = write_json(output/'common-migration-input.json',dict(schema_version=1,
        kind='common-recovery-migration',model='VIMAR30805',ota_profile=2,
        recovery_signed=record(recovery),recovery_config=record(artifacts/'recovery.config'),
        audited_loader_config=record(loader_config),loader_compatibility_registry=record(registry_path),
        allowed_loaders=allowed_raw))
    # Build from the same frozen source tree, keeping the tool's strict input gates.
    previous_root=common.ROOT
    try:
        common.ROOT=source_root
        migration_result=common.build_unsigned_migration(migration_input,output/'common-migration')
    finally:
        common.ROOT=previous_root
    migration=sign('migration',Path(migration_result['unsigned_image_path']))
    report['migration_build_manifest']=record(migration_result['manifest_path'])

    host=output/'primary-validation.so'
    run(['cc','-shared','-fPIC','-std=c11','-Wno-deprecated-declarations','-DOTA_IMAGE_HOST',
         '-DOTA_IMAGE_AUTH_ONLY','-I'+str(firmware/'ota'),'-I'+str(firmware/'recovery/src'),
         firmware/'ota/ota_image.c',firmware/'recovery/src/recovery_primary.c','-lcrypto','-o',host], 'host-verifier-build.log')
    validator=ctypes.CDLL(str(host)).recovery_primary_validate
    validator.argtypes=[ctypes.c_void_p,ctypes.c_size_t]
    results={}
    for name,path in [('main',main),('migration',migration),('recovery',recovery)]:
        data=path.read_bytes();results[name]=validator(data,len(data))
    if results['main']!=0 or results['migration']==0 or results['recovery']==0:
        raise ValueError('real signed image failed recovery exit role policy')
    report['real_primary_exit_verification']=results

    ota_input=write_json(output/'ota-input.json',dict(schema_version=1,ota_profile=2,
        image_role='main',version=VERSIONS['main'],minimum_source_version='0.5.7+7',encoder='bt2-48-32',
        manufacturer_code=0xfff1,image_type=0x3085,hardware_min=1,hardware_max=1,
        current_signed=record(current_main),candidate_signed=record(main),candidate_unsigned=record(main_raw),
        recovery_signed=record(recovery),pair_bindings=record(registry_path)))
    ota=package_release(ota_input,output/'ota')
    ota_report=json.loads(Path(ota['report_path']).read_text())
    report['ota']=dict(ota,budget=ota_report['budget'])
    report['status']='signed common candidate pair and bootstrap built; physical qualification pending'
    report['firmware_source_contains_keys']=False
    report['public_candidate_artifacts']=[str(path.relative_to(output)) for path in [main,recovery,migration]]
    report['builder_sha256']=sha(Path(__file__).read_bytes())
    save()
    return report_path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--loader-authorizations',required=True,type=Path)
    parser.add_argument('--current-main',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    print(build_candidate(args.loader_authorizations,args.current_main,args.output))


if __name__=='__main__':
    main()
