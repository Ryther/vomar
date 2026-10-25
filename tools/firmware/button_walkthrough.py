#!/usr/bin/env python3
"""Prove guidate dei due ingressi recovery sul Vimar BLE già installato.

Non programma firmware, non usa SWD e non invia comandi alla luce.
Richiede il bond BlueZ già predisposto per questo preciso Vimar.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
ADDRESS = ''  # Offline API sentinel; live runs require --address.
MAIN_HASH = 'e5999bf00845c57c7510db19282cefeb3cfc680218b68f14a0a2cc13a162bb0a'
RECOVERY_HASH = '655780b2d74866e945938f17644db42097545ca433aed31d42c1e5257321ef84'
SMP_SERVICE = '8d53dc1d-1db7-4cd3-868b-8a527460aa84'
STEPS = (
    ('runtime_both', 'Entrambi i pulsanti durante il funzionamento',
     'ORA tieni premuti insieme UP e DOWN per almeno 6 secondi, poi rilasciali.\n'
     'Non togliere alimentazione. Attendo la recovery BLE...'),
    ('power_up', 'UP durante l’accensione',
     'ORA scollega la USB che alimenta il DK/Vimar. Tieni premuto UP sul VIMAR,\n'
     'ricollega la USB e tieni UP finché lo script ti dice di rilasciarlo.\n'
     'Non toccare la chiavetta Bluetooth del PC. Attendo la recovery BLE...'),
)


def validate_images(images, main_hash=MAIN_HASH, recovery_hash=RECOVERY_HASH):
    if not any(i['slot'] == 1 and i['active'] and i['hash'] == recovery_hash for i in images):
        raise ValueError('Hash/slot della recovery diversi dalla revisione Vimar verificata.')
    if not any(i['slot'] == 0 and not i['active'] and i['hash'] == main_hash for i in images):
        raise ValueError('Applicazione principale diversa dalla revisione 0.4.5 attesa.')


def validate_main(status):
    if not (status['simulated'] and status['software_recovery'] and
            not status['stock_output_enabled'] and not status['output_fault']):
        raise ValueError('Il firmware non è nel profilo simulato atteso: prova interrotta.')


async def wait_for_main(read, timeout, emit, delay=2,
                        retry_errors=(RuntimeError, OSError, TimeoutError)):
    """Wait for actual authenticated readiness, never interpret delay as success."""
    async with asyncio.timeout(timeout):
        attempt = 0
        while True:
            attempt += 1
            try:
                status = await read()
            except ValueError:
                raise
            except retry_errors as exc:
                emit('main_wait_retry', attempt=attempt, error=repr(exc))
                print(f'BLE Vimar non ancora disponibile (tentativo {attempt}); attendo...',
                      flush=True)
                await asyncio.sleep(delay)
                continue
            validate_main(status)
            return status


class Journal:
    def __init__(self, folder, address=ADDRESS, main_hash=MAIN_HASH, recovery_hash=RECOVERY_HASH):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        if any((folder / n).exists() for n in ('events.jsonl', 'results.json')):
            raise FileExistsError('La cartella contiene già risultati: usa una cartella nuova.')
        self.result = dict(started=datetime.now(timezone.utc).isoformat(), address=address,
                           outcome='running', expected_main_hash=main_hash,
                           expected_recovery_hash=recovery_hash,
                           single_button_events='not_observable_in_current_firmware',
                           steps={key: {'outcome': 'not_run'} for key, _, _ in STEPS})
        self.emit('session_started')
        self.save()

    def save(self):
        temporary = self.folder / 'results.json.tmp'
        temporary.write_text(json.dumps(self.result, indent=2, ensure_ascii=False) + '\n')
        temporary.replace(self.folder / 'results.json')

    def emit(self, event, **data):
        row = dict(time=datetime.now(timezone.utc).isoformat(), event=event, **data)
        with (self.folder / 'events.jsonl').open('a') as output:
            output.write(json.dumps(row, ensure_ascii=False) + '\n')


async def terminal_prompt(text):
    """Linux TTY input without a blocked executor thread on Ctrl+C."""
    print('\n' + text, end=' ', flush=True)
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def ready():
        line = sys.stdin.readline()
        if not future.done():
            if line:
                future.set_result(line.strip().lower())
            else:
                future.set_exception(EOFError('Terminale chiuso'))
    loop.add_reader(sys.stdin.fileno(), ready)
    try:
        return await future
    finally:
        loop.remove_reader(sys.stdin.fileno())


class BLEProbe:
    def __init__(self, timeout, emit=lambda *args, **kwargs: None, *, address=ADDRESS, main_hash=MAIN_HASH, recovery_hash=RECOVERY_HASH):
        if not address:
            raise ValueError("Explicit BLE address required")
        self.address, self.main_hash, self.recovery_hash = address, main_hash, recovery_hash
        self.timeout = timeout
        self.emit = emit
        spec = importlib.util.spec_from_file_location('research_console',
                                                      Path(__file__).with_name('research_console.py'))
        self.console = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.console)

    async def main_status(self):
        from bleak.exc import BleakError
        print(f'Cerco l’app BLE del Vimar (attesa massima {self.timeout} secondi)...', flush=True)
        self.emit('main_wait_started', timeout=self.timeout)
        return await wait_for_main(self._read_main_status, self.timeout, self.emit,
                                   retry_errors=(RuntimeError, OSError, TimeoutError, BleakError))

    async def _read_main_status(self):
        from bleak import BleakClient
        async with BleakClient(self.address, timeout=20) as client:
            if client.services.get_service(self.console.SERVICE) is None:
                raise RuntimeError('App principale assente: il Vimar potrebbe essere in recovery.')
            sequence = 2381
            await client.write_gatt_char(self.console.COMMAND,
                                        self.console.encode(0, sequence), response=True)
            result = self.console.decode(bytes(await client.read_gatt_char(self.console.COMMAND)),
                                         0, sequence)
            validate_main(result)
            return result

    async def gesture(self, text, emit):
        from bleak import BleakScanner
        from smpclient import SMPClient
        from smpclient.transport.ble import SMPBLETransport
        from smpclient.requests.image_management import ImageStatesRead
        from smpclient.generics import error
        found = asyncio.Event()

        def advertisement(device, adv):
            if device.address.upper() == self.address.upper() and (
                    adv.local_name == 'Vimar30805-Rescue' or
                    SMP_SERVICE in [u.lower() for u in adv.service_uuids]):
                found.set()

        async with asyncio.timeout(self.timeout):
            async with BleakScanner(detection_callback=advertisement):
                # Start listening before the action cue: human timing is not critical.
                emit('gesture_armed', instruction=text)
                print('\n' + text, flush=True)
                await found.wait()
                print('Recovery rilevata: ORA rilascia tutti i pulsanti. Verifico gli hash...',
                      flush=True)
            emit('recovery_advertisement_observed')
            # Advertising is not proof: authenticate and check both firmware hashes.
            async with SMPClient(SMPBLETransport(), self.address, timeout_s=30) as client:
                state = await client.request(ImageStatesRead())
                if error(state):
                    raise RuntimeError(str(state))
                images = [dict(slot=i.slot, active=i.active, version=i.version,
                               hash=i.hash.hex()) for i in state.images]
                validate_images(images, self.main_hash, self.recovery_hash)
                return images

    async def return_to_main(self, emit):
        from smpclient import SMPClient
        from smpclient.transport.ble import SMPBLETransport
        from smpclient.requests.image_management import ImageStatesRead
        from smpclient.requests.os_management import ResetWrite
        from smpclient.generics import error
        async with SMPClient(SMPBLETransport(), self.address, timeout_s=30) as client:
            state = await client.request(ImageStatesRead())
            if error(state):
                raise RuntimeError(str(state))
            validate_images([dict(slot=i.slot, active=i.active, hash=i.hash.hex()) for i in state.images], self.main_hash, self.recovery_hash)
            emit('reset_request_sending')
            result = await client.request(ResetWrite())
            if error(result):
                raise RuntimeError(str(result))
            emit('reset_acknowledged')
        await asyncio.sleep(3)
        return await self.main_status()


async def walkthrough(probe, journal, prompt=terminal_prompt):
    current = None
    try:
        initial = await probe.main_status()
        validate_main(initial)
        journal.emit('initial_main_verified', status=initial)
        for key, title, instruction in STEPS:
            current = key
            record = journal.result['steps'][key]
            print('\n' + title, flush=True)
            answer = await prompt('Premi Invio per armare la prova, oppure scrivi SALTA:')
            if answer == 'salta':
                record['outcome'] = 'skipped'
                journal.emit('step_skipped', step=key)
                journal.save()
                continue
            if answer:
                raise ValueError('Risposta non valida: usa Invio o SALTA. Nessuna azione avviata.')
            # Each attempt must begin in the main app, never already in rescue.
            validate_main(await probe.main_status())
            record['outcome'] = 'running'
            journal.save()
            images = await probe.gesture(instruction, journal.emit)
            validate_images(images)
            record['images'] = images
            record['recovery_observed'] = True
            journal.emit('recovery_hashes_verified', step=key, images=images)
            journal.save()
            print('Recovery corretta verificata via BLE.', flush=True)
            confirmation = await prompt('Hai eseguito il gesto indicato, senza altri reset? Scrivi SI o NO:')
            record['operator_confirmed'] = confirmation in ('si', 'sì')
            journal.emit('operator_confirmation', step=key, answer=confirmation,
                         confirmed=record['operator_confirmed'])
            journal.save()
            answer = await prompt('Rilascia tutti i pulsanti. Invio per riavviare l’app dal recupero BLE:')
            if answer:
                raise ValueError('Rientro non confermato: nessun reset inviato, il Vimar resta in recovery.')
            record['return_requested'] = True
            journal.emit('return_to_main_requested', step=key)
            journal.save()
            record['main_after'] = await probe.return_to_main(journal.emit)
            validate_main(record['main_after'])
            record['outcome'] = 'passed' if record['operator_confirmed'] else 'unconfirmed'
            journal.emit('step_finished', step=key, outcome=record['outcome'])
            journal.save()
        complete = all(r['outcome'] == 'passed' for r in journal.result['steps'].values())
        journal.result['outcome'] = 'passed' if complete else 'incomplete'
        return 0 if complete else 2
    except (KeyboardInterrupt, asyncio.CancelledError):
        journal.result['outcome'] = 'cancelled'
        if current and journal.result['steps'][current]['outcome'] in ('not_run', 'running'):
            journal.result['steps'][current]['outcome'] = 'cancelled'
        journal.emit('session_cancelled', step=current)
        print('\nAnnullato: rilascia i pulsanti. Risultati parziali salvati. '
              'Nessun ulteriore riavvio verrà inviato.', flush=True)
        return 130
    except Exception as exc:
        journal.result['outcome'] = 'failed'
        detail = f'{type(exc).__name__}: {exc}'
        if current:
            journal.result['steps'][current].update(outcome='failed', error=detail)
        journal.emit('session_failed', step=current, error=detail)
        print(f'\nProva NON validata: {detail}\nRilascia i pulsanti. '
              'Nessun ulteriore riavvio verrà inviato; consulta gli eventi salvati.', flush=True)
        return 1
    finally:
        journal.result['finished'] = datetime.now(timezone.utc).isoformat()
        journal.save()
        print(f"\nEsito: {journal.result['outcome']}\nRisultati: {journal.folder / 'results.json'}",
              flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--address', help='Indirizzo BLE del dispositivo da provare')
    parser.add_argument('--main-hash', help='Hash SMP atteso della MAIN simulata (64 cifre esadecimali)')
    parser.add_argument('--recovery-hash', help='Hash SMP atteso della recovery (64 cifre esadecimali)')
    parser.add_argument('--timeout', type=int, default=180,
                        help='Secondi massimi per ogni attesa BLE (default 180).')
    parser.add_argument('--output', type=Path, help='Nuova cartella dei risultati.')
    parser.add_argument('--plan', action='store_true', help='Mostra le istruzioni senza usare BLE.')
    args = parser.parse_args()
    if not 15 <= args.timeout <= 600:
        parser.error('--timeout deve essere tra 15 e 600 secondi.')
    if args.plan:
        for _, title, text in STEPS:
            print(title + '\n' + text + '\n')
        return 0
    if not args.address: parser.error('--address è richiesto per una prova reale')
    import re
    for name in ('main_hash', 'recovery_hash'):
        if not re.fullmatch(r'[0-9a-f]{64}', getattr(args, name) or ''):
            parser.error('--' + name.replace('_', '-') + ' richiede64 cifre esadecimali minuscole')
    if not sys.stdin.isatty():
        parser.error('Avvia da un terminale interattivo; --plan mostra soltanto le istruzioni.')
    folder = args.output or ROOT / 'experiments' / (
        'vimar-button-check-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    journal = Journal(folder, args.address, args.main_hash, args.recovery_hash)
    print('Prova sul VIMAR, non sui pulsanti del DK. Lascia la molletta collegata.\n'
          'Mantieni l’attuale alimentazione da banco; non collegare la rete elettrica.\n'
          'Il monitoraggio parte al segnale ORA, dopo il tuo Invio.\n'
          'Puoi saltare una prova con SALTA o interrompere con Ctrl+C.\n'
          'Sono verificati i gesti recovery; le singole pressioni non sono telemetrizzate.\n'
          f'Cartella risultati: {folder}', flush=True)
    return asyncio.run(walkthrough(BLEProbe(args.timeout, journal.emit, address=args.address, main_hash=args.main_hash, recovery_hash=args.recovery_hash), journal))


if __name__ == '__main__':
    sys.exit(main())
