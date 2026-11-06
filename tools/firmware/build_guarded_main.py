"""Build compact guarded MAIN, without signing or rebuilding recovery."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from tools.firmware.build_typed_common_candidate import (
    fault_build_identity, public_record, require_ownership_main, require_release_main, sha,
)
from tools.firmware.toolchain_paths import toolchain_paths
from tools.firmware.validate_recovery import read_config
from tools.release.component_versions import firmware_owner

ROOT = Path(__file__).resolve().parents[2]
HELPERS = ('check_ownership_link.py', 'prepare_diag_batch_sdk.py', 'check_diag_batch_link.py',
           'prepare_compact_sdk.py')
CONFIG = '''CONFIG_VIMAR_LOADER_RUNTIME_V2=y
CONFIG_MAIN_STACK_SIZE=12288
CONFIG_MCUBOOT_SIGNATURE_KEY_FILE=""
CONFIG_MCUBOOT_GENERATE_UNSIGNED_IMAGE=n
CONFIG_VIMAR_FAULT_DIAGNOSTICS=y
CONFIG_VIMAR_ZIGBEE_OWNERSHIP_GUARD=y
CONFIG_ZIGBEE_ENABLE_TRACES=n
CONFIG_LTO=y
CONFIG_ISR_TABLES_LOCAL_DECLARATION=y
CONFIG_VIMAR_ZIGBEE_DIAGNOSTIC_BATCH=y
CONFIG_VIMAR_LOOP_TRACE=n
CONFIG_NCS_BOOT_BANNER=n
CONFIG_BOOT_BANNER=n
CONFIG_PRINTK=n
'''


def prepare(output, pair_bindings, loader_bindings):
    version = firmware_owner((ROOT / 'firmware/VERSION').read_text())
    inputs = {'main.conf': CONFIG.encode(), 'builder.py': Path(__file__).read_bytes()}
    for name, path in (('main-pair.h', pair_bindings), ('loader-contracts.h', loader_bindings)):
        data = Path(path).read_bytes()
        if not 1 <= len(data) <= 65536:
            raise ValueError('Bounded reviewed binding header required')
        inputs[name] = data
    out = Path(output).resolve()
    if out.exists() or Path(output).is_symlink() or out.is_relative_to(ROOT / 'inputs'):
        raise ValueError('Output must be new and outside inputs')
    out.mkdir(parents=True)
    shutil.copytree(ROOT / 'firmware', out / 'source/firmware',
                    ignore=shutil.ignore_patterns('keys', 'build', '__pycache__', '*.orig'))
    helpers = out / 'source/tools/firmware'
    helpers.mkdir(parents=True)
    for name in HELPERS:
        shutil.copy2(ROOT / 'tools/firmware' / name, helpers / name)
    hashes = {str(path.relative_to(out / 'source')): sha(path.read_bytes())
              for path in sorted((out / 'source').rglob('*')) if path.is_file()}
    build_id = fault_build_identity(hashes, {'main': version}, inputs)
    generated = out / 'generated'
    generated.mkdir()
    for name in ('main-pair.h', 'loader-contracts.h'):
        (generated / name).write_bytes(inputs[name])
    (out / 'main.conf').write_bytes(inputs['main.conf'])
    (generated / 'fault-build-id.h').write_text(
        '#include <stdint.h>\nstatic const uint8_t vimar_fault_build_id[16]={'
        + ','.join(str(b) for b in build_id) + '};\n')
    return dict(version=version, build_id=build_id.hex(), source_sha256=hashes,
                inputs_sha256={name: sha(data) for name, data in inputs.items()},
                hardware_access=False, signed=False, recovery_rebuilt=False,
                loader_rebuilt=False, qualified=False, status='prepared')


def build(output, pair_bindings, loader_bindings):
    report = prepare(output, pair_bindings, loader_bindings)
    out = Path(output).resolve()
    fw = out / 'source/firmware'
    paths = toolchain_paths()
    overlays = [fw / name for name in ('boards/nrf52840dk_nrf52840_ota.overlay',
                'research/vimar-candidate.overlay', 'boards/fault-diagnostics.overlay',
                'boards/loop-trace.overlay', 'boards/allocation-trace.overlay')]
    extras = [fw / 'vimar_zigbee.conf', fw / 'research/vimar-candidate.conf',
              fw / 'ota/crypto.conf', out / 'main.conf']
    command = [str(paths['west']), 'build', '--pristine', '--no-sysbuild', '-b',
               'nrf52840dk/nrf52840', str(fw), '-d', str(out / 'build'),
               '--target', 'vimar_diag_batch_admission', '--',
               '-DCONF_FILE=' + str(fw / 'prj_split_ota.conf'),
               '-DEXTRA_CONF_FILE=' + ';'.join(map(str, extras)),
               '-DDTC_OVERLAY_FILE=' + ';'.join(map(str, overlays)),
               *['-D' + key + '=' + str(out / 'generated' / name) for key, name in (
                   ('VIMAR_OTA_PAIR_BINDINGS_HEADER', 'main-pair.h'),
                   ('VIMAR_LOADER_CONTRACT_BINDINGS_HEADER', 'loader-contracts.h'),
                   ('VIMAR_FAULT_BUILD_ID_HEADER', 'fault-build-id.h'))]]
    report.update(command=command, cwd=str(paths['sdk']), status='building')
    manifest = out / 'build-report.json'

    def save():
        manifest.write_text(json.dumps(report, indent=2) + '\n')

    save()
    try:
        env = {**os.environ, 'PATH': str(paths['west'].parent) + os.pathsep + os.environ['PATH']}
        with (out / 'build.log').open('xb') as stream:
            result = subprocess.run(command, cwd=paths['sdk'], env=env,
                                    stdout=stream, stderr=subprocess.STDOUT, timeout=1800)
        report['returncode'] = result.returncode
        result.check_returncode()
        native = out / 'build'
        cfg = read_config(native / 'zephyr/.config')
        for line in CONFIG.splitlines():
            key, value = line.split('=', 1)
            if cfg.get(key, 'n') != value:
                raise ValueError('MAIN configuration mismatch: ' + key)
        if cfg.get('CONFIG_BT') == 'y':
            raise ValueError('MAIN must keep its Zigbee radio profile')
        report['fault_hooks'] = require_release_main(native, out, cfg)
        report['ownership'] = require_ownership_main(native)
        audit = json.loads((native / 'diag-batch-link-audit.json').read_text())
        if (audit.get('passed') is not True or
                audit.get('sha256') != sha((native / 'zephyr/zephyr.elf').read_bytes())):
            raise ValueError('Diagnostic admission does not match MAIN ELF')
        report['diagnostic_admission'] = public_record(native / 'diag-batch-link-audit.json')
        report['elf'] = public_record(native / 'zephyr/zephyr.elf')
        report['status'] = 'native admission passed; unsigned and unqualified'
    except Exception as exc:
        report.update(status='failed', error=str(exc))
        raise
    finally:
        save()
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ('output', 'pair-bindings', 'loader-bindings'):
        parser.add_argument('--' + field, type=Path, required=True)
    print(build(**vars(parser.parse_args())))


if __name__ == '__main__':
    main()
