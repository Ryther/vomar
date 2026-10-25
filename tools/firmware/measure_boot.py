#!/usr/bin/env python3
"""Misura guidata dell'avvio BLE del Vimar; nessun SWD/reset/aggiornamento."""
import argparse
import asyncio
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
ADDRESS = ''  # Offline API sentinel; live runs require --address.


class RecoveryDetected(ValueError):
    """The radio is reachable but serves the updater instead of the main app."""


def firmware_mode(service_uuids):
    services = {value.lower() for value in service_uuids}
    if 'fde30805-c001-4a40-8d00-308050000001' in services:
        return 'main'
    if '8d53dc1d-1db7-4cd3-868b-8a527460aa84' in services:
        return 'recovery'
    return 'unknown'


def load_helper():
    spec = importlib.util.spec_from_file_location('button_helpers',
                                                 Path(__file__).with_name('button_walkthrough.py'))
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper


def latency_bounds(cue, confirmation, observed):
    if confirmation < cue or observed < cue:
        raise ValueError('Ordine temporale non valido')
    return dict(lower_seconds=max(0, observed-confirmation), upper_seconds=observed-cue)


def new_kernel_observed(before, after, on_cue):
    old_latest = before['response_end'] - before['uptime_ms']/1000
    new_earliest = after['request_start'] - after['uptime_ms']/1000
    return new_earliest > old_latest and new_earliest >= on_cue


class Advertisements:
    def __init__(self, address=ADDRESS):
        self.address = address.upper()
        self.last = None
        self.count = 0
        self.cue = None
        self.first = None
        self.device = None
        self.ready = asyncio.Event()

    def arm(self, cue):
        self.cue = cue
        self.first = None
        self.device = None
        self.ready.clear()

    def observe(self, address, observed_at, name, device=None):
        if address.upper() != self.address:
            return
        self.last = observed_at
        self.count += 1
        if self.cue is not None and observed_at >= self.cue and self.first is None:
            self.first = dict(observed_at=observed_at, name=name)
            self.device = device
            self.ready.set()


async def wait_for_power_off(tracker, confirmed, off_seconds, quiet_seconds, timeout,
                             emit, report, *, clock=time.monotonic, pause=asyncio.sleep):
    """Observe radio silence and a minimum pause; never assert electrical discharge."""
    last_report = None
    async with asyncio.timeout(timeout):
        while True:
            now = clock()
            elapsed = max(0, now-confirmed)
            silence = max(0, now-max(confirmed, tracker.last if tracker.last is not None else confirmed))
            state = dict(elapsed_seconds=elapsed, silence_seconds=silence,
                         remaining_minimum_seconds=max(0, off_seconds-elapsed),
                         required_silence_seconds=quiet_seconds,
                         last_advertisement_at=tracker.last,
                         observed_advertisements=tracker.count,
                         advertisement_after_off_confirmation=(
                             tracker.last is not None and tracker.last >= confirmed),
                         electrical_power_off_confirmed=False)
            ready = elapsed >= off_seconds and silence >= quiet_seconds
            if last_report is None or now-last_report >= 5 or ready:
                report(state)
                emit('power_off_observation_progress', **state)
                last_report = now
            if ready:
                emit('power_off_observation_completed', **state)
                return state
            await pause(1)


def report_power_off(state):
    age = state['silence_seconds']
    if state['advertisement_after_off_confirmation']:
        radio = f'Vimar rilevato da BlueZ dopo lo scollegamento; ultimo aggiornamento {age:.0f} s fa'
    else:
        radio = f'Nessun aggiornamento BLE/BlueZ del Vimar da {age:.0f} s dopo la conferma'
    print(f"{radio} | pausa {state['elapsed_seconds']:.0f} s | "
          f"attesa minima restante {state['remaining_minimum_seconds']:.0f} s | "
          f"silenzio richiesto {state['required_silence_seconds']:.0f} s", flush=True)


class Journal:
    def __init__(self, folder, address=ADDRESS):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        if any((folder/n).exists() for n in ('events.jsonl', 'results.json')):
            raise FileExistsError('Cartella già usata: scegli una nuova cartella')
        self.result = dict(outcome='running', address=address, phase='preflight',
                           timing_basis='clock monotonic; power actions confirmed by operator',
                           radio_detection_source='Bleak/BlueZ callbacks; may include cached property changes, not raw HCI packets',
                           physical_power_switch_not_instrumented=True)
        self.emit('session_started')
        self.save()

    def save(self):
        p = self.folder/'results.json.tmp'
        p.write_text(json.dumps(self.result, indent=2, ensure_ascii=False)+'\n')
        p.replace(self.folder/'results.json')

    def emit(self, event, **data):
        with (self.folder/'events.jsonl').open('a') as f:
            f.write(json.dumps(dict(time=datetime.now(timezone.utc).isoformat(),
                                    monotonic=time.monotonic(), event=event, **data),
                               ensure_ascii=False)+'\n')


async def wait_status(read, timeout, emit, delay=2,
                      retry_errors=(RuntimeError, OSError, TimeoutError), recover=None):
    helper = load_helper()
    async with asyncio.timeout(timeout):
        attempt = 0
        while True:
            attempt += 1
            try:
                result = await read()
            except ValueError:
                raise
            except retry_errors as exc:
                emit('ble_retry', attempt=attempt, error=repr(exc))
                if recover is not None:
                    await recover(exc)
                print(f'Attendo risposta BLE del Vimar: tentativo {attempt}...', flush=True)
                await asyncio.sleep(delay)
                continue
            helper.validate_main(result)
            return result


async def read_after_discovery(scanner, probe, device, timeout, emit, delay=2,
                               retry_errors=(RuntimeError, OSError, TimeoutError)):
    # Avoid a nested implicit discovery while our measurement scanner is active.
    await scanner.stop()
    emit('discovery_stopped_before_connection')
    print('Vimar rilevato. Ricerca terminata; verifico la connessione autenticata...', flush=True)

    async def recover(exc):
        if getattr(exc, 'dbus_error', None) == 'org.bluez.Error.InProgress':
            emit('pending_target_connection_cancel_requested')
            print('BlueZ segnala una connessione pendente: la annullo solo sul Vimar e riprovo.', flush=True)
            await probe.cancel_pending(device)
            emit('pending_target_connection_cancelled')

    return await wait_status(lambda: probe.read(device), timeout, emit, delay,
                             retry_errors, recover)


class Probe:
    def __init__(self, address=ADDRESS):
        if not address:
            raise ValueError("Explicit BLE address required")
        self.address = address.upper()
        helper = load_helper()
        self.console = helper.BLEProbe(30, address=self.address).console

    async def read(self, device=None):
        from bleak import BleakClient, BleakScanner
        if device is None:
            device = await BleakScanner.find_device_by_address(self.address, timeout=15)
            if device is None:
                raise RuntimeError('Vimar non rilevato durante la ricerca BLE')
        if device.address.upper() != self.address:
            raise ValueError('Dispositivo diverso dal Vimar atteso')
        async with BleakClient(device, timeout=15) as c:
            mode = firmware_mode(service.uuid for service in c.services)
            if mode == 'recovery':
                raise RecoveryDetected('Recovery BLE raggiunta; applicazione principale non attiva')
            if mode != 'main':
                raise RuntimeError('Console principale e servizio recovery assenti')
            sequence = 3471
            start = time.monotonic()
            await c.write_gatt_char(self.console.COMMAND,
                                   self.console.encode(0, sequence), response=True)
            result = self.console.decode(bytes(await c.read_gatt_char(self.console.COMMAND)),
                                         0, sequence)
            result.update(request_start=start, response_end=time.monotonic())
            return result

    async def cancel_pending(self, device):
        from dbus_fast import BusType, Message, MessageType
        from dbus_fast.aio import MessageBus
        if device.address.upper() != self.address:
            raise ValueError('Rifiutata disconnessione di un altro dispositivo')
        path = device.details['path']
        if not path.startswith('/org/bluez/') or not path.endswith('/dev_'+self.address.replace(':', '_')):
            raise ValueError('Percorso BlueZ del Vimar inatteso')
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        try:
            reply = await bus.call(Message(destination='org.bluez', path=path,
                                           interface='org.bluez.Device1', member='Disconnect'))
            if reply is None:
                raise RuntimeError('Nessuna risposta alla cancellazione della connessione pendente')
            if reply.message_type == MessageType.ERROR and reply.error_name not in (
                    'org.bluez.Error.NotConnected', 'org.freedesktop.DBus.Error.UnknownObject'):
                raise RuntimeError(f'Disconnect Vimar: {reply.error_name} {reply.body}')
        finally:
            bus.disconnect()


async def run(args, journal):
    from bleak import BleakScanner
    from bleak.exc import BleakError
    helper = load_helper()
    probe = Probe(args.address)
    retry_errors = (RuntimeError, OSError, TimeoutError, BleakError)
    task = None
    try:
        print('Verifico prima che il Vimar sia acceso e risponda via BLE. Non spegnerlo ancora.', flush=True)
        baseline = await wait_status(probe.read, args.timeout, journal.emit, retry_errors=retry_errors)
        journal.result['baseline'] = baseline
        journal.emit('initial_status_verified', status=baseline)
        journal.save()
        tracker = Advertisements(args.address)

        def callback(device, adv):
            before = tracker.first
            tracker.observe(device.address, time.monotonic(), adv.local_name, device)
            if before is None and tracker.first is not None:
                journal.result['first_advertisement'] = tracker.first
                journal.emit('first_advertisement', **tracker.first)
                journal.save()
                print(f"\nPrimo annuncio Vimar dopo {tracker.first['observed_at']-tracker.cue:.2f} s "
                      'dal segnale ACCENDI.', flush=True)

        async with BleakScanner(detection_callback=callback) as scanner:
            print('Controllo che lo scanner riceva aggiornamenti BLE/BlueZ dal Vimar acceso...', flush=True)
            async with asyncio.timeout(args.timeout):
                while tracker.last is None:
                    await asyncio.sleep(.2)
            journal.emit('initial_advertisement_verified', observed_at=tracker.last)
            await helper.terminal_prompt('Prepara il cavo USB di alimentazione. Invio quando sei pronto:')
            journal.result['phase'] = 'power_off'
            journal.emit('power_off_cue')
            print('\n>>> ORA SCOLLEGA la USB che alimenta il DK/Vimar. Lascia fermi contatti e chiavetta Bluetooth. <<<', flush=True)
            await helper.terminal_prompt('Quando lo hai spento, premi Invio per confermare:')
            off_confirm = time.monotonic()
            journal.result['operator_off_confirmed_at'] = off_confirm
            journal.emit('operator_off_confirmed')
            journal.save()
            print(f'Lascialo scollegato: almeno {args.off_seconds} s di pausa e '
                  f'{args.quiet_seconds} s consecutivi senza annunci. Non ricollegare ancora.', flush=True)
            observation = await wait_for_power_off(
                tracker, off_confirm, args.off_seconds, args.quiet_seconds,
                args.off_seconds+args.timeout, journal.emit, report_power_off)
            journal.result['power_off_observation'] = observation
            journal.save()
            print('Pausa minima e silenzio BLE osservati. Spegnimento elettrico non accertato.', flush=True)
            await helper.terminal_prompt('Preparati a riaccendere SENZA premere tasti sul Vimar. Invio quando pronto:')
            # Recheck after the human prompt too: advertising may have resumed
            # while the operator prepared to reconnect the cable.
            journal.result['power_off_observation'] = await wait_for_power_off(
                tracker, off_confirm, args.off_seconds, args.quiet_seconds,
                args.timeout, journal.emit, report_power_off)
            cue = time.monotonic()
            tracker.arm(cue)
            journal.result.update(phase='power_on', on_cue=cue)
            journal.emit('power_on_cue')
            journal.save()

            async def measure():
                async with asyncio.timeout(args.timeout):
                    await tracker.ready.wait()
                    status = await read_after_discovery(scanner, probe, tracker.device,
                                                        args.timeout, journal.emit,
                                                        retry_errors=retry_errors)
                    journal.result['authenticated_status'] = status
                    journal.emit('authenticated_response', status=status)
                    journal.save()
                    print(f"\nRisposta autenticata dopo {status['response_end']-cue:.2f} s "
                          'dal segnale ACCENDI.', flush=True)
                    return status

            # Monitor and authentication run while the operator reaches for Enter.
            task = asyncio.create_task(measure())
            print('\n>>> ORA ACCENDI il DK/Vimar, SENZA premere pulsanti sul Vimar. <<<', flush=True)
            await helper.terminal_prompt('Appena acceso, premi Invio per registrare la tua conferma:')
            confirmation = time.monotonic()
            journal.result['operator_on_confirmed_at'] = confirmation
            journal.emit('operator_on_confirmed')
            journal.save()
            print(f'Attendo annuncio e risposta BLE (massimo {args.timeout} s dal segnale)...', flush=True)
            status = await task
            adv_bounds = latency_bounds(cue, confirmation, tracker.first['observed_at'])
            response_bounds = latency_bounds(cue, confirmation, status['response_end'])
            restarted = new_kernel_observed(baseline, status, cue)
            journal.result.update(phase='finished', advertisement_latency=adv_bounds,
                                  authenticated_response_latency=response_bounds,
                                  new_kernel_start_observed=restarted,
                                  outcome='measured' if restarted else 'restart_not_confirmed')
            journal.emit('measurement_finished', new_kernel_start_observed=restarted)
            print(f"\nPrimo annuncio: tra {adv_bounds['lower_seconds']:.2f} e "
                  f"{adv_bounds['upper_seconds']:.2f} secondi dalla riaccensione dichiarata.\n"
                  f"Risposta autenticata: tra {response_bounds['lower_seconds']:.2f} e "
                  f"{response_bounds['upper_seconds']:.2f} secondi.\n"
                  f"Uptime applicazione alla risposta: {status['uptime_ms']/1000:.2f} s.\n"
                  f"Nuovo avvio kernel osservato: {'SI' if restarted else 'NON CONFERMATO'}.", flush=True)
            return 0 if restarted else 2
    except RecoveryDetected as exc:
        journal.result.update(outcome='recovery_detected', firmware_mode='recovery',
                              new_kernel_start_observed=None)
        journal.emit('recovery_detected', detail=str(exc))
        print('\nIl Vimar risponde con il servizio recovery BLE. Il LED temporaneo lì è spento.\n'
              'Non è un timeout radio né una prova di avvio dell’app principale.\n'
              'Lascialo acceso; nessun reset o aggiornamento inviato.', flush=True)
        return 2
    except (KeyboardInterrupt, asyncio.CancelledError):
        journal.result['outcome'] = 'cancelled'
        journal.emit('session_cancelled')
        print('\nAnnullato. Nessun comando di reset o scrittura inviato.', flush=True)
        return 130
    except Exception as exc:
        journal.result.update(outcome='failed', error=f'{type(exc).__name__}: {exc}')
        journal.emit('session_failed', error=journal.result['error'])
        print(f"\nMisura NON completata: {journal.result['error']}", flush=True)
        return 1
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        journal.result['finished'] = datetime.now(timezone.utc).isoformat()
        journal.save()
        print(f"\nEsito: {journal.result['outcome']}\nRisultati: {journal.folder/'results.json'}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--address', help='Indirizzo BLE esatto del dispositivo da misurare')
    parser.add_argument('--timeout', type=int, default=300, help='Attesa massima BLE in secondi (default300).')
    parser.add_argument('--off-seconds', type=int, default=120,
                        help='Pausa minima con USB scollegata (default120 s).')
    parser.add_argument('--quiet-seconds', type=int, default=10,
                        help='Silenzio BLE consecutivo richiesto prima di riaccendere (default10 s).')
    parser.add_argument('--output', type=Path, help='Cartella nuova per JSON e JSONL.')
    parser.add_argument('--plan', action='store_true', help='Mostra la sequenza senza accesso hardware.')
    args = parser.parse_args()
    if not 30 <= args.timeout <= 1800:
        parser.error('--timeout deve essere tra30 e1800 secondi')
    if not 1 <= args.off_seconds <= 1800 or not 1 <= args.quiet_seconds <= 300:
        parser.error('--off-seconds deve essere tra1 e1800; --quiet-seconds tra1 e300')
    if args.plan:
        print('1. Verifica BLE iniziale.\n2. Segnale SPEGNI e conferma Invio.\n'
              f'3. Monitor BLE visibile: almeno{args.off_seconds}s scollegato e '
              f'{args.quiet_seconds}s consecutivi senza annunci.\n4. Segnale ACCENDI e conferma Invio.\n'
              '5. Misura primo annuncio e risposta autenticata, confronta uptime.\n'
              '6. Salva risultati; nessun SWD, reset, upload o modifica dei bond.')
        return 0
    if not args.address: parser.error('--address è richiesto per una misura reale')
    if not sys.stdin.isatty():
        parser.error('Usa un terminale interattivo, oppure --plan.')
    folder = args.output or ROOT/'experiments'/('vimar-boot-timing-'+
                         datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    journal = Journal(folder, args.address)
    print('Ferma gli altri script BLE e il monitor SWD prima della prova.\n'
          'Mantieni i collegamenti e l’alimentazione da banco attuali. Nessuna pressione sui tasti.\n'
          'Per togliere davvero alimentazione al DK, escludi anche la pila: la sola USB non basta se alimenta VDD.\n'
          'I rilevamenti BlueZ possono includere dati cached; il nuovo avvio viene verificato tramite uptime.\n'
          'I segnali e le conferme delimitano l’incertezza della manovra manuale.\n'
          f'Risultati: {folder}', flush=True)
    return asyncio.run(run(args, journal))


if __name__ == '__main__':
    sys.exit(main())
