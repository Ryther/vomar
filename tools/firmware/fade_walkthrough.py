#!/usr/bin/env python3
"""Confronto guidato delle rampe: Invio prima dei comandi, esiti salvati."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
IEEE = ''  # Offline API sentinel; live runs require --ieee.
URL = None  # Live runs require --url.
CONFIG = ['min_level', 'max_level', 'rise_transition_ms', 'fall_transition_ms',
          'ramp_start_level', 'ramp_end_level', 'initial_on_delay_ms', 'output_mode',
          'auto_off_mode', 'auto_off_duration_s']
STATUS = ['schema_version', 'state', 'brightness', 'applied_output_on',
          'applied_output_level', 'transition_active', 'fault_code', 'timer_active', 'target_level']
PROTECTION = ['p031_enabled', 'p031_sample_valid', 'p031_output_blocked', 'p031_trip_count']
STEPS = [
    'A1: spegnimento della lampada, se accesa.',
    'A2: accensione da OFF al livello di prova con la rampa configurata; annotazione.',
    'B1: spegnimento prima della seconda prova.',
    'B2: accensione diretta al minimo, transizione zero; conferma visiva del minimo.',
    'B3: dal minimo, salita allo stesso livello finale con la stessa rampa; annotazione.',
    'Ripristino guidato del livello memorizzato e dello stato iniziali, se richiesto.',
]


def restored_state_matches(original, final):
    remembered = original.get('target_level', original['brightness'])
    return (final.get('state') == original['state'] and final.get('fault_code') == 0
            and final.get('target_level') == remembered
            and (original['state'] == 'OFF' or final.get('brightness') == remembered))


def parse_startup_holds(value):
    try:
        holds = tuple(int(part) for part in value.split(','))
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Usare millisecondi interi separati da virgole') from exc
    if not 1 <= len(holds) <= 6 or any(not 10 <= hold <= 5000 for hold in holds):
        raise argparse.ArgumentTypeError('Da1 a6 pause, ciascuna tra10 e5000ms')
    return holds


def require_protection(state, expected_trips):
    if (state.get('p031_enabled') is not True or state.get('p031_sample_valid') is not True
            or state.get('p031_output_blocked') is not False
            or state.get('p031_trip_count') != expected_trips or state.get('fault_code') != 0):
        raise RuntimeError('Monitor P0.31 non pronto o intervento rilevato: prova fermata')


def require_off(state):
    if (state.get('state') != 'OFF' or state.get('applied_output_on') != 'OFF'
            or state.get('transition_active') is not False):
        raise RuntimeError('La lampada non risulta più spenta: prova fermata prima dell’accensione')


def require_minimum(state, minimum):
    if (state.get('state') != 'ON' or state.get('applied_output_on') != 'ON'
            or state.get('applied_output_level') != minimum
            or state.get('transition_active') is not False or state.get('timer_active')):
        raise RuntimeError('La lampada non risulta più stabile al minimo: nessuna salita inviata')


async def prompt(text):
    print('\n' + text, end=' ', flush=True)
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    def ready():
        line = sys.stdin.readline()
        if not future.done():
            if line:
                future.set_result(line.strip())
            else:
                future.set_exception(EOFError('Terminale chiuso'))
    loop.add_reader(sys.stdin.fileno(), ready)
    try:
        answer = await future
    finally:
        loop.remove_reader(sys.stdin.fileno())
    if answer.lower() in ('q', 'stop', 'esci'):
        raise InterruptedError('Prova fermata dall’utente')
    return answer


class Journal:
    def __init__(self, folder, ieee=IEEE):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=False)
        self.result = {'ieee': ieee, 'started_at': datetime.now(timezone.utc).isoformat(),
                       'outcome': 'running', 'observations': {}, 'commands': [],
                       'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       'software_feedback_is_not_optical_measurement': True}
        self.save()
    def save(self):
        p = self.folder / 'results.json'
        p.write_text(json.dumps(self.result, indent=2, ensure_ascii=False) + '\n')
        p.chmod(0o600)
    def emit(self, event, **data):
        p = self.folder / 'events.jsonl'
        with p.open('a') as f:
            f.write(json.dumps({'time': time.time(), 'event': event, **data}, ensure_ascii=False) + '\n')
        p.chmod(0o600)


class Probe:
    def __init__(self, cookie, timeout, journal, *, ieee=IEEE, url=URL, origin=None):
        self.cookie, self.timeout, self.journal = cookie, timeout, journal
        self.ieee, self.url, self.origin = ieee, url, origin
        self.state, self.device = {}, None
        self.sequence = 0
        self.error = None
        self.changed = asyncio.Condition()
    async def __aenter__(self):
        import websockets
        if not self.ieee or not self.url:
            raise ValueError('Explicit Zigbee IEEE and WebSocket URL required')
        self.ws = await websockets.connect(self.url, origin=self.origin,
            additional_headers={'Cookie': self.cookie}, max_size=8*1024*1024, close_timeout=1)
        self.reader = asyncio.create_task(self.pump())
        try:
            await self.wait(lambda: self.device is not None, self.timeout)
        except BaseException:
            await self.__aexit__()
            raise
        return self
    async def __aexit__(self, *_):
        self.reader.cancel()
        await asyncio.gather(self.reader, return_exceptions=True)
        await self.ws.close()
    def observe_state(self, state):
        self.state = state
        self.sequence += 1
        self.journal.emit('device_state', state={k: state.get(k) for k in CONFIG+STATUS+PROTECTION+['last_seen', 'action', 'update']})
        try:
            if hasattr(self, 'expected_protection_trips'):
                require_protection(state, self.expected_protection_trips)
            for key, expected in getattr(self, 'expected_config', {}).items():
                if state.get(key) != expected:
                    raise RuntimeError(f'Parametro cambiato durante la prova: {key}')
            if hasattr(self, 'holding_minimum'):
                require_minimum(state, self.holding_minimum)
        except RuntimeError as exc:
            self.error = self.error or exc
    async def pump(self):
        try:
            async for raw in self.ws:
                m = json.loads(raw)
                p = m.get('payload')
                if isinstance(p, str):
                    try: p = json.loads(p)
                    except ValueError: continue
                topic = m.get('topic')
                async with self.changed:
                    if topic == 'bridge/devices':
                        matches = [d for d in p if d.get('ieee_address') == self.ieee]
                        if len(matches) != 1 or matches[0].get('model_id') != 'Vimar30805':
                            raise RuntimeError('Dispositivo selezionato non identificato univocamente come Vimar custom sulla rete selezionata')
                        self.device = matches[0]
                    elif self.device and topic == self.device['friendly_name'] and isinstance(p, dict):
                        self.observe_state(p)
                    elif topic == 'bridge/logging' and isinstance(p, dict) and p.get('level') == 'error':
                        message = p.get('message', '')
                        if self.ieee in message or (self.device and self.device['friendly_name'] in message):
                            self.journal.emit('z2m_error', message=message)
                            # Keep the actual Z2M failure visible: delivery errors
                            # and malformed-command responses need different diagnoses.
                            self.error = self.error or RuntimeError(message)
                    self.changed.notify_all()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = self.error or exc
        else:
            self.error = self.error or ConnectionError('Connessione Z2M chiusa')
        async with self.changed:
            self.changed.notify_all()
    async def wait(self, predicate, timeout):
        async with asyncio.timeout(timeout):
            async with self.changed:
                await self.changed.wait_for(lambda: self.error is not None or predicate())
                if self.error:
                    raise self.error
    def fresh(self, sequence, sent):
        try: stamp = datetime.fromisoformat(self.state.get('last_seen', '')).timestamp()
        except ValueError: return False
        return self.sequence > sequence and stamp >= sent-1
    async def read(self, keys):
        marker, sent = self.sequence, time.time()
        self.journal.emit('read_requested', keys=keys)
        await self.ws.send(json.dumps({'topic': self.ieee+'/get', 'payload': {k: '' for k in keys}}))
        await self.wait(lambda: self.fresh(marker, sent) and all(self.state.get(k) is not None for k in keys), self.timeout)
        # Let the remaining small batch finish before starting another read.
        await asyncio.sleep(0.8)
        if self.error: raise self.error
        if self.state.get('fault_code', 0): raise RuntimeError('Il dimmer segnala un errore: prova fermata')
        return dict(self.state)
    async def set(self, payload, on, level=None):
        if self.error: raise self.error
        if hasattr(self, 'expected_protection_trips'):
            require_protection(self.state, self.expected_protection_trips)
        for key, expected in getattr(self, 'expected_config', {}).items():
            if self.state.get(key) != expected:
                raise RuntimeError(f'Parametro cambiato durante la prova: {key}. Nessun altro comando inviato')
        marker, sent = self.sequence, time.time()
        self.journal.result['commands'].append({'sent_at': sent, 'payload': payload})
        self.journal.save()
        self.journal.emit('command_sent', payload=payload)
        await self.ws.send(json.dumps({'topic': self.ieee+'/set', 'payload': payload}))
        def applied():
            s = self.state
            if s.get('fault_code', 0): raise RuntimeError('Errore durante il comando: prova fermata')
            if hasattr(self, 'expected_protection_trips'):
                require_protection(s, self.expected_protection_trips)
            return (self.fresh(marker, sent) and s.get('state') == ('ON' if on else 'OFF')
                and s.get('applied_output_on') == ('ON' if on else 'OFF')
                and s.get('transition_active') is False
                and (not on or s.get('applied_output_level') == level))
        duration = max(self.state.get('rise_transition_ms', 0), self.state.get('fall_transition_ms', 0))
        await self.wait(applied, max(self.timeout, (duration+self.state.get('initial_on_delay_ms', 0))/1000+10))
        self.journal.emit('software_output_reached', on=on, level=level)
        print('Comando applicato secondo il firmware; annota ciò che hai visto sulla lampada.', flush=True)


async def enter(text):
    answer = await prompt(text + '\nInvio = esegui; q = termina:')
    if answer:
        raise InterruptedError('Comando non eseguito: per procedere usare soltanto Invio')


async def prepare_comparison(probe, journal, target_percent=None):
    print('Controllo iniziale in sola lettura...', flush=True)
    await probe.read(['schema_version'])  # One liveness read before queueing configuration requests.
    for i in range(0, len(CONFIG+STATUS), 3):
        await probe.read((CONFIG+STATUS)[i:i+3])
    original = dict(probe.state)
    if original['schema_version'] < 4 or original['output_mode'] != 'dimmable':
        raise RuntimeError('Serve firmware schema4 in modalità dimmable')
    if original['timer_active'] or original['transition_active'] or original['auto_off_mode'] != 'disabled':
        raise RuntimeError('Timer, transizione o spegnimento automatico attivi: nessun comando inviato. Attendi o disattivali per la prova')
    minimum, maximum = original['min_level'], original['max_level']
    target = round(target_percent*254/100) if target_percent is not None else original.get('target_level', original['brightness'])
    if target_percent is None and target <= minimum: target = min(82, maximum)
    if not minimum < target <= maximum:
        raise ValueError('Il livello di prova deve essere maggiore del minimo e non superare il massimo')
    journal.result.update(baseline={k: original.get(k) for k in CONFIG+STATUS},
                          target_level=target, friendly_name=probe.device['friendly_name'])
    probe.expected_config = {key: original[key] for key in CONFIG}
    journal.save()
    print(f"Dispositivo: {probe.device['friendly_name']} ({getattr(probe, 'ieee', IEEE)})\n"
          f"Minimo: {minimum*100/254:.1f}%; livello di prova: {target*100/254:.1f}%.\n"
          f"Rampa salita: {original['rise_transition_ms']} ms; discesa: {original['fall_transition_ms']} ms.\n"
          'Durante le prove usa questo terminale e osserva la luce; lascia invariati i parametri.', flush=True)
    return original, target


async def walkthrough(probe, journal, target_percent=None):
    original, target = await prepare_comparison(probe, journal, target_percent)
    minimum = original['min_level']
    async def off(label):
        await enter(label + ' — Porto la lampada a OFF con il comportamento attuale.')
        if probe.state['state'] != 'OFF' or probe.state['applied_output_on'] != 'OFF' or probe.state['transition_active']:
            await probe.set({'state': 'OFF'}, False)
        else:
            print('La lampada risulta già spenta.')
    async def note(key, text):
        value = await prompt(text)
        journal.result['observations'][key] = value
        journal.save()
    await off('A1')
    await enter('A2 — Guarda la lampada: accendo da OFF con la rampa attuale.')
    await probe.set({'state': 'ON', 'brightness': target}, True, target)
    await note('normal_start', 'A — Hai visto un salto? Una pausa al buio? Quanto sembrava durare la salita? Scrivi e premi Invio:')
    await off('B1')
    await enter('B2 — Accendo direttamente al minimo con transizione zero. NON aumento ancora il livello.')
    await probe.set({'state': 'ON', 'brightness': minimum, 'transition': 0}, True, minimum)
    answer = await prompt('La lampada è visibilmente accesa e stabile al minimo? Scrivi s oppure n:')
    journal.result['observations']['minimum_visible_and_stable'] = answer.lower() in ('s', 'si', 'sì')
    journal.save()
    if not journal.result['observations']['minimum_visible_and_stable']:
        await note('minimum_failure', 'Descrivi cosa vedi; la salita B verrà saltata:')
    else:
        await note('minimum_start', 'B minimo — Si è accesa subito oppure dopo un’attesa? Scrivi e premi Invio:')
        await enter('B3 — Ora parto dal minimo già acceso e salgo allo STESSO livello finale, con la STESSA rampa.')
        if (probe.state['applied_output_on'] != 'ON' or
                probe.state['applied_output_level'] != minimum or probe.state['transition_active']):
            raise RuntimeError('La lampada non risulta più stabile al minimo: confronto B interrotto')
        await probe.set({'state': 'ON', 'brightness': target}, True, target)
        await note('warm_ramp', 'B — Salita più continua, uguale o peggiore rispetto ad A? Descrivi e premi Invio:')
    await restore_comparison(probe, journal, original)


async def restore_comparison(probe, journal, original):
    answer = await prompt('Prove terminate. Invio = ripristino guidato dello stato e livello iniziali; lascia = mantieni lo stato attuale:')
    if not answer:
        old_level = original.get('target_level', original['brightness'])
        if probe.state['brightness'] != old_level or (original['state'] == 'ON' and probe.state['state'] != 'ON'):
            await enter(f'Ripristino livello memorizzato {old_level*100/254:.1f}%: la lampada sarà accesa a quel livello.')
            await probe.set({'state': 'ON', 'brightness': old_level, 'transition': 0}, True, old_level)
        if original['state'] == 'OFF' and probe.state['state'] != 'OFF':
            await enter('Ripristino dello stato iniziale OFF: spengo senza rampa.')
            await probe.set({'state': 'OFF', 'transition': 0}, False)
        final = await probe.read(['state', 'brightness', 'target_level', 'fault_code'])
        if not restored_state_matches(original, final):
            raise RuntimeError('Ripristino non confermato; controllare i risultati prima di altri comandi')
        journal.result['restored'] = True
    else:
        journal.result['restored'] = False
    journal.result['outcome'] = 'completed'
    journal.save()


async def run_startup_trial(probe, journal, target, minimum, hold_ms):
    expected_trips = getattr(probe, 'expected_protection_trips', probe.state.get('p031_trip_count'))
    require_protection(probe.state, expected_trips)
    require_off(probe.state)
    timing = {'additional_hold_requested_ms': hold_ms, 'physical_hold_measured': False,
              'clock': 'host_monotonic', 'phase': 'minimum_requested'}
    journal.result.setdefault('startup_timings', []).append(timing)
    journal.save()
    started = time.monotonic()
    await probe.set({'state': 'ON', 'brightness': minimum, 'transition': 0}, True, minimum)
    confirmed = time.monotonic()
    timing.update(phase='minimum_confirmed', minimum_confirmation_ms=(confirmed-started)*1000)
    journal.save()
    probe.holding_minimum = minimum
    try:
        await asyncio.sleep(hold_ms/1000)
        if getattr(probe, 'error', None):
            raise probe.error
        require_protection(probe.state, expected_trips)
        require_minimum(probe.state, minimum)
    finally:
        del probe.holding_minimum
    sending = time.monotonic()
    timing.update(phase='target_requested', send_gap_ms=(sending-started)*1000,
                  additional_hold_actual_ms=(sending-confirmed)*1000)
    journal.save()
    await probe.set({'state': 'ON', 'brightness': target}, True, target)
    timing.update(phase='target_confirmed', total_ms=(time.monotonic()-started)*1000)
    journal.emit('startup_trial_completed', **timing)
    journal.save()


async def startup_walkthrough(probe, journal, holds, target_percent=None):
    original, target = await prepare_comparison(probe, journal, target_percent)
    if original['schema_version'] < 5:
        raise RuntimeError('La serie con pause richiede schema5 e monitor P0.31')
    for i in range(0, len(PROTECTION), 2):
        await probe.read(PROTECTION[i:i+2])
    expected_trips = probe.state.get('p031_trip_count')
    if not isinstance(expected_trips, int):
        raise RuntimeError('Conteggio P0.31 non disponibile')
    require_protection(probe.state, expected_trips)
    if original['rise_transition_ms'] <= 0 or original['initial_on_delay_ms'] != 0:
        raise RuntimeError('Per il confronto serve una rampa salita non nulla e ritardo iniziale0; nessun parametro modificato')
    probe.expected_protection_trips = expected_trips
    journal.result.update(mode='startup_holds', additional_holds_ms=list(holds),
                          protection_baseline={k: probe.state[k] for k in PROTECTION},
                          physical_hold_measured=False)
    journal.save()
    print('Le pause sono aggiuntive DOPO la conferma software del minimo. Il tempo fisico al minimo\n'
          'non è misurato: il ritardo Zigbee si somma. Registro anche gli intervalli delle richieste.\n'
          'Ogni Invio della serie autorizza minimo → pausa → salita; Ctrl+C interrompe anche la pausa.', flush=True)

    async def off(label):
        await enter(label + ' — Porto la lampada a OFF senza rampa e attendo 3 secondi.')
        if probe.state['state'] != 'OFF' or probe.state['applied_output_on'] != 'OFF' or probe.state['transition_active']:
            await probe.set({'state': 'OFF', 'transition': 0}, False)
        await asyncio.sleep(3)
        require_off(probe.state)
        journal.emit('off_dwell_completed', requested_ms=3000)

    await off('A1')
    await enter('A2 — Riferimento: accendo da OFF al livello finale con la rampa attuale. Guarda la luce.')
    require_off(probe.state)
    await probe.set({'state': 'ON', 'brightness': target}, True, target)
    journal.result['observations']['startup_reference'] = await prompt('Riferimento — Salto iniziale, pausa al buio e continuità della salita: descrivi e premi Invio:')
    journal.save()
    for index, hold in enumerate(holds, 1):
        await off(f'{index}.1')
        await enter(f'{index}.2 — Accendo al minimo, aspetto la conferma +{hold}ms, poi salgo allo stesso livello. Guarda la luce.')
        await run_startup_trial(probe, journal, target, original['min_level'], hold)
        timing = journal.result['startup_timings'][-1]
        print(f"Intervallo tra richieste: {timing['send_gap_ms']:.0f}ms; pausa aggiuntiva: {timing['additional_hold_actual_ms']:.0f}ms.", flush=True)
        journal.result['observations'][f'startup_hold_{index}_{hold}ms'] = await prompt('Rispetto al riferimento: salto minore/uguale/maggiore? Hai visto la permanenza al minimo? Descrivi e premi Invio:')
        journal.save()
    await restore_comparison(probe, journal, original)


async def run(args, journal):
    cookie = args.cookie.read_text().strip()
    if cookie.lower().startswith('cookie:'): cookie = cookie[7:].strip()
    if not cookie: raise ValueError('File cookie vuoto')
    try:
        async with Probe(cookie, args.timeout, journal, ieee=args.ieee, url=args.url, origin=args.origin) as probe:
            if args.startup_holds_ms is None:
                await walkthrough(probe, journal, args.target_percent)
            else:
                await startup_walkthrough(probe, journal, args.startup_holds_ms, args.target_percent)
    except BaseException as exc:
        journal.result['outcome'] = 'interrupted' if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError, InterruptedError, EOFError)) else 'failed'
        message = ('Nessuna risposta confermata entro il timeout; verifica che il dimmer sia raggiungibile in Zigbee2MQTT'
                   if isinstance(exc, TimeoutError) else str(exc) or type(exc).__name__)
        journal.result['error'] = message.replace(cookie, '<redacted>')
        journal.save()
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ieee', help='IEEE Zigbee esatto del dispositivo da provare')
    p.add_argument('--url', help='URL WebSocket API Zigbee2MQTT, ws:// oppure wss://')
    p.add_argument('--origin', help='Origin HTTP richiesto dal proxy, se necessario')
    p.add_argument('--cookie', type=Path, default=ROOT/'work/private/z2m-cookie.txt')
    p.add_argument('--output', type=Path, help='Cartella nuova; default experiments/fade-walkthrough/<data UTC>')
    p.add_argument('--target-percent', type=float, help='Livello finale comune; default luminosità memorizzata, oppure32.3%% se al minimo')
    p.add_argument('--startup-holds-ms', type=parse_startup_holds, help='Serie guidata di pause aggiuntive al minimo, es.100,300,1000; richiede schema5')
    p.add_argument('--timeout', type=float, default=30)
    p.add_argument('--dry-run', action='store_true', help='Mostra il percorso senza rete, credenziali o comandi alla lampada')
    args = p.parse_args()
    if args.target_percent is not None and not 0 < args.target_percent <= 100:
        p.error('--target-percent deve essere maggiore di0 e non superare100')
    if not 5 <= args.timeout <= 120: p.error('--timeout deve essere tra5 e120 secondi')
    if args.dry_run:
        print('ANTEPRIMA — nessuna connessione o comando. Dispositivo:', args.ieee or '(da configurare)')
        if args.startup_holds_ms is None:
            print('\n'.join(STEPS))
        else:
            print('Riferimento OFF → livello finale con la rampa attuale; poi per ogni pausa:')
            for hold in args.startup_holds_ms:
                print(f'Invio: OFF senza rampa +3s; altro Invio: minimo → conferma → +{hold}ms → stesso livello finale.')
            print('Pause aggiuntive alla latenza Zigbee, non tempi fisici misurati. Ripristino finale guidato.')
        return 0
    if not args.ieee: p.error('--ieee è richiesto per una prova reale')
    if not args.url: p.error('--url è richiesto per una prova reale')
    import re
    if not re.fullmatch(r'0x[0-9a-f]{16}', args.ieee): p.error('--ieee richiede0x e16 cifre esadecimali minuscole')
    if not args.url.startswith(('ws://', 'wss://')): p.error('--url deve usare ws:// o wss://')
    if not sys.stdin.isatty():
        p.error('Eseguire in un terminale interattivo: non inviare una sequenza di Invio tramite pipe')
    folder = args.output or ROOT/'experiments/fade-walkthrough'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    journal = Journal(folder, ieee=args.ieee)
    print('Confronto visuale del dimmer. Ogni fase richiede Invio. q o Ctrl+C fermano senza ulteriori comandi.\n'
          'Il programma cambia stato/luminosità della lampada; non aggiorna firmware né parametri.\n'
          f'Risultati: {folder}', flush=True)
    try:
        asyncio.run(run(args, journal))
    except (Exception, KeyboardInterrupt) as exc:
        if journal.result['outcome'] == 'running':
            journal.result.update(outcome='failed', error=type(exc).__name__)
            journal.save()
        print('\nProva fermata:', journal.result.get('error') or type(exc).__name__)
        if not journal.result['commands']:
            print('Nessun comando alla lampada è stato inviato.')
        else:
            print('Nessun ripristino automatico dopo lo stop; verifica lo stato attuale della luce.')
        print('Risultati salvati in:', folder)
        return 1
    print('\nProva completata. Dimmi «fatto» e leggerò i risultati in:', folder)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
