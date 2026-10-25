#!/usr/bin/env python3
"""Build research main applications only; never accesses physical hardware."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def initial_install_image(provisioning_path):
    """Prepare (never program) explicit empty storage for a first stock replacement."""
    from intelhex import IntelHex
    image = IntelHex(str(provisioning_path))
    if any(address >= 0xf0000 for address in image.addresses()):
        raise ValueError('Provisioning components overlap storage or non-image registers.')
    # Old stock bootloader bytes can occupy these new settings/NVRAM partitions.
    # A normal three-image update must preserve storage; initial replacement is
    # a distinct, explicit artifact which requires physical-device approval.
    image.puts(0xf0000, b'\xff' * 0x10000)
    destination = provisioning_path.with_name('research-initial-install.hex')
    image.write_hex_file(str(destination))
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=('dk', 'vimar-candidate'), default='dk')
    parser.add_argument('--stock-output', action='store_true',
                        help='Compile experimental physical PWM/GPIO backend instead of simulation.')
    parser.add_argument('--with-loader', action='store_true',
                        help='Also build matching loader/recovery and a bounded provisioning HEX.')
    args = parser.parse_args()
    build = ROOT / 'work' / ('build-ble-research-' + args.target +
                             ('-stock-output' if args.stock_output else ''))
    app = ROOT / 'firmware/research'
    overlay = [ROOT / 'firmware/boards/nrf52840dk_nrf52840_ota.overlay']
    if args.target == 'vimar-candidate':
        overlay.append(app / 'vimar-candidate.overlay')
    command = [str(ROOT / 'work/ncs-venv/bin/west'), 'build', '--no-sysbuild', '--pristine',
               '-b', 'nrf52840dk/nrf52840', str(app), '-d', str(build), '--',
               '-DDTC_OVERLAY_FILE=' + ';'.join(map(str, overlay)),
               '-DCONFIG_RESEARCH_SOFTWARE_RECOVERY=y',
               '-DCONFIG_MCUBOOT_SIGNATURE_KEY_FILE="' + str(ROOT / 'firmware/keys/dev-private.pem') + '"',
               '-DCONFIG_MCUBOOT_IMGTOOL_SIGN_VERSION="0.4.0+0"']
    if args.target == 'vimar-candidate':
        command.append('-DEXTRA_CONF_FILE=' + str(app / 'vimar-candidate.conf'))
    if args.stock_output:
        command.append('-DCONFIG_RESEARCH_STOCK_OUTPUT=y')
    log = ROOT / 'work' / (build.name + '.log')
    print('Build log:', log, flush=True)
    with log.open('w') as file:
        subprocess.run(command, cwd=ROOT / 'work/ncs-zigbee', stdout=file,
                       stderr=subprocess.STDOUT, check=True)
    image = build / 'zephyr/zephyr.signed.bin'
    subprocess.run([str(ROOT / 'work/ncs-venv/bin/python'),
                    str(ROOT / 'work/ncs-zigbee/bootloader/mcuboot/scripts/imgtool.py'),
                    'verify', '-k', str(ROOT / 'firmware/keys/dev-public.pem'), str(image)], check=True)
    manifest = dict(target=args.target, simulated=not args.stock_output,
                    hardware_validated=False, requires_matching_software_recovery_loader=True,
                    command=command, image=str(image.relative_to(ROOT)),
                    size=image.stat().st_size, sha256=hashlib.sha256(image.read_bytes()).hexdigest())
    if args.with_loader:
        from intelhex import IntelHex
        loader_build = ROOT / 'work' / ('build-ble-research-loader-' + args.target)
        loader_conf = [app / 'loader-software-recovery.conf']
        if args.target == 'vimar-candidate':
            loader_conf.append(app / 'vimar-candidate.conf')
        loader_command = [str(ROOT / 'work/ncs-venv/bin/west'), 'build', '--sysbuild',
                          '--pristine', '-b', 'nrf52840dk/nrf52840', str(ROOT / 'firmware'),
                          '-d', str(loader_build), '--', '-DFILE_SUFFIX=ota',
                          '-Dmcuboot_EXTRA_CONF_FILE=' + ';'.join(map(str, loader_conf))]
        if args.target == 'vimar-candidate':
            loader_command += ['-DVIMAR_RESEARCH_BOARD_OVERLAY=' + str(app / 'vimar-candidate.overlay'),
                               '-Dvimar_recovery_EXTRA_CONF_FILE=' + str(app / 'vimar-candidate.conf')]
        loader_log = ROOT / 'work' / (loader_build.name + '.log')
        print('Loader build log:', loader_log, flush=True)
        with loader_log.open('w') as file:
            subprocess.run(loader_command, cwd=ROOT / 'work/ncs-zigbee', stdout=file,
                           stderr=subprocess.STDOUT, check=True)
        combined = IntelHex()
        parts = [(loader_build / 'mcuboot/zephyr/zephyr.hex', 0, 0xc000),
                 (build / 'zephyr/zephyr.signed.hex', 0xc000, 0xb0000),
                 (loader_build / 'vimar_recovery/zephyr/zephyr.signed.hex', 0xb0000, 0xf0000)]
        part_records = []
        for part, low, high in parts:
            parsed = IntelHex(str(part))
            if not all(low <= address < high for address in parsed.addresses()):
                raise RuntimeError(f'Image crosses permitted partition: {part}')
            combined.merge(parsed, overlap='error')
            if part.name.endswith('.signed.hex'):
                subprocess.run([str(ROOT / 'work/ncs-venv/bin/python'),
                                str(ROOT / 'work/ncs-zigbee/bootloader/mcuboot/scripts/imgtool.py'),
                                'verify', '-k', str(ROOT / 'firmware/keys/dev-public.pem'),
                                str(part)], check=True)
            part_records.append(dict(path=str(part.relative_to(ROOT)),
                                     sha256=hashlib.sha256(part.read_bytes()).hexdigest()))
        rescue = loader_build / 'vimar_recovery/zephyr/zephyr.signed.bin'
        subprocess.run([str(ROOT / 'work/ncs-venv/bin/python'),
                        str(ROOT / 'work/ncs-zigbee/bootloader/mcuboot/scripts/imgtool.py'),
                        'verify', '-k', str(ROOT / 'firmware/keys/dev-public.pem'), str(rescue)], check=True)
        combined_path = build / 'research-provisioning.hex'
        combined.write_hex_file(str(combined_path))
        initial_path = initial_install_image(combined_path)
        manifest.update(loader_command=loader_command, components=part_records,
                        provisioning_hex=str(combined_path.relative_to(ROOT)),
                        provisioning_sha256=hashlib.sha256(combined_path.read_bytes()).hexdigest(),
                        initial_install_hex=str(initial_path.relative_to(ROOT)),
                        initial_install_sha256=hashlib.sha256(initial_path.read_bytes()).hexdigest(),
                        initial_install_storage_reset=dict(start='0xf0000', end_exclusive='0x100000',
                                                          value='0xff', uicr_included=False))
    (build / 'research-artifact.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
