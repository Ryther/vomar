#!/usr/bin/env python3
"""Poll a selected Vimar’s read-only SWD identity; Ctrl+C stops monitoring."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]


def identity(output):
    match = re.search(r'0x10000060:\s+([0-9a-fA-F]{8})\s+([0-9a-fA-F]{8})', output)
    part = re.search(r'0x10000100:\s+([0-9a-fA-F]{8})', output)
    if match and part and int(part[1], 16) == 0x52840:
        return tuple(int(value, 16) for value in match.groups())
    return None


def failure_message(output, returncode=None):
    if 'No J-Link device found' in output:
        return 'DK/J-Link non rilevato via USB: controlla cavo e alimentazione del DK'
    if 'already opened' in output.lower() or 'already in use' in output.lower():
        return 'J-Link occupato da un altro programma: chiudi gli altri monitor/debugger'
    partial = 'SWD DPIDR 0x2ba01477' in output
    partial_message = 'RISPOSTA PARZIALE SWD (DPIDR valido), identità Vimar non letta'
    if returncode is not None and returncode < 0:
        prefix = partial_message + '; ' if partial else ''
        return prefix + f'OpenOCD terminato dal segnale {-returncode}: vedi log'
    if 'parity mismatch' in output:
        return 'Errore di parità SWD: comunicazione non affidabile, identità Vimar non letta'
    if partial:
        return partial_message
    voltage = re.search(r'VTarget = ([0-9.]+ V)', output)
    if 'cannot read IDR' in output:
        supply = f"; VTarget {voltage[1]}" if voltage else ''
        return f'J-Link presente{ supply }; SWD non risponde: verifica collegamenti e alimentazione Vimar'
    if 'timeout' in output.lower():
        return 'Timeout OpenOCD: consulta il log per distinguere USB e SWD'
    return 'Lettura SWD fallita: consulta il log indicato sopra'


def capture_commands(folder, expected_id):
    # Re-check the exact target before collecting any device memory.
    def quote(path):
        return '"' + str(path).replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('[', '\\[') + '"'
    return [
        'set ids [read_memory 0x10000060 32 2]; '
        f'if {{[lindex $ids 0] != {expected_id[0]:#x} || [lindex $ids 1] != {expected_id[1]:#x}}} '
        '{error "Not the known Vimar: capture refused"}',
        'mdw 0x40000400 1',  # RESETREAS
        'mdw 0xe000edf0 1',  # DHCSR: observation only
        'mdw 0xe000ed08 1',  # VTOR
        'mdw 0xe000ed28 6',  # fault status/address registers
        'mdw 0xe0002000 1',  # FPB control
        'mdw 0x4001e800 3',  # ACL region 0
        f'dump_image {quote(folder / "ram-first-16k.bin")} 0x20000000 0x4000',
        f'dump_image {quote(folder / "uicr.bin")} 0x10001000 0x1000',
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jlink-serial', required=True, help='Seriale esatto del J-Link da usare')
    parser.add_argument('--uid', nargs=2, type=lambda value: int(value, 16), required=True,
                        help='Due parole FICR DEVICEID in esadecimale, nell’ordine degli indirizzi')
    parser.add_argument('--interval', type=float, default=2,
                        help='Pausa tra tentativi, in secondi (default: 2).')
    parser.add_argument('--capture-state', action='store_true',
                        help='Alla prima lettura Vimar salva registri/RAM/UICR senza halt e termina.')
    args = parser.parse_args()
    if not args.jlink_serial.isdigit(): parser.error('--jlink-serial deve contenere solo cifre')
    if any(not 0 <= value <= 0xffffffff for value in args.uid): parser.error('--uid richiede due parole32-bit')
    if not 0.2 <= args.interval <= 3600:
        parser.error('--interval deve essere tra 0.2 e 3600 secondi')
    folder = ROOT / 'experiments/swd-contact-monitor'
    folder.mkdir(parents=True, exist_ok=True)
    log_path = folder / (datetime.now().strftime('%Y%m%dT%H%M%S%f') + '.log')
    capture_folder = folder / log_path.stem
    if args.capture_state:
        capture_folder.mkdir()
    command = ['openocd', '-f', 'interface/jlink.cfg', '-c', 'adapter serial ' + args.jlink_serial,
               '-c', 'transport select swd', '-f', 'target/nrf52.cfg',
               '-c', 'adapter speed 100', '-c', 'init',
               '-c', 'mdw 0x10000060 2', '-c', 'mdw 0x10000100 1']
    if args.capture_state:
        command += sum((['-c', c] for c in capture_commands(capture_folder, args.uid)), [])
        command += ['-c', 'echo VIMAR_STATE_CAPTURE_COMPLETE']
    command += ['-c', 'shutdown']
    print('VERDE = identità del Vimar confermata.\n'
          + ('Cattura automatica dello stato, poi termina. Lascia i collegamenti fermi.\n'
             if args.capture_state else 'Il monitor continua dopo il primo successo; Ctrl+C termina.\n')
          +
          f'Solo letture, nessun halt/reset/erase/program. Log: {log_path}', flush=True)
    streak = 0
    try:
        with log_path.open('a') as log:
            while True:
                stamp = datetime.now().strftime('%H:%M:%S')
                returncode = None
                try:
                    result = subprocess.run(command, capture_output=True, text=True,
                                            timeout=20 if args.capture_state else 5)
                    returncode = result.returncode
                    output = result.stdout + result.stderr
                    output += f'\nMonitor: OpenOCD returncode={returncode}\n'
                    device = identity(output) if result.returncode == 0 or args.capture_state else None
                except subprocess.TimeoutExpired:
                    output = 'OpenOCD timeout dopo ' + ('20' if args.capture_state else '5') + ' secondi\n'
                    device = None
                log.write(f'\n[{stamp}]\n{output}')
                log.flush()
                if device == tuple(args.uid):
                    if streak == 0:
                        print('\a', end='', flush=True)
                    streak += 1
                    print(f'\033[1;32m[{stamp}] OK VIMAR — {streak} letture consecutive\033[0m', flush=True)
                    if args.capture_state:
                        expected = {'ram-first-16k.bin': 0x4000, 'uicr.bin': 0x1000}
                        complete = (returncode == 0 and 'VIMAR_STATE_CAPTURE_COMPLETE' in output and
                                    all((capture_folder/n).exists() and
                                        (capture_folder/n).stat().st_size == size
                                        for n, size in expected.items()))
                        if complete:
                            records = {n: hashlib.sha256((capture_folder/n).read_bytes()).hexdigest()
                                       for n in expected}
                            (capture_folder/'capture.json').write_text(json.dumps(dict(
                                completed=datetime.now().isoformat(), deviceid=[hex(v) for v in device],
                                no_halt_reset_or_flash_write=True, running_memory_not_atomic=True,
                                sha256=records, log=str(log_path)), indent=2)+'\n')
                            print(f'CATTURA COMPLETATA: {capture_folder}\nMonitor terminato.', flush=True)
                            return
                        print('Identità letta, cattura incompleta: riprovo senza dichiararla riuscita.', flush=True)
                else:
                    was_connected = streak > 0
                    streak = 0
                    if device is not None:
                        message = 'SWD OK, ma è un altro nRF52840: ' + ' '.join(f'{v:08x}' for v in device)
                    else:
                        message = failure_message(output, returncode)
                        if was_connected:
                            message = 'CONTATTO PERSO — ' + message
                    print(f'\033[33m[{stamp}] {message}\033[0m', flush=True)
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print('\nMonitor terminato.')
    except FileNotFoundError:
        parser.exit(1, 'openocd non trovato: esegui dal terminale del devcontainer.\n')


if __name__ == '__main__':
    main()
