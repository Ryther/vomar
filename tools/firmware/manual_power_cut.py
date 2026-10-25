#!/usr/bin/env python3
"""Interactive power-loss probe for the isolated, already provisioned research DK.

No SWD programming, erase, bootloader update or automatic reset. Writes only the
main application via the pinned BLE recovery. Run from an interactive terminal.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
RECOVERY_HASH = 'bc808b8dc418de2a727c4c27056b03e48eaf44d4182483d8867932e2368987e2'


async def cut_window(offsets, size, threshold, emit):
    """Signal once, keep transmitting, and stop short of finishing if no cut occurs."""
    signalled = False
    offset = 0
    try:
        async for offset in offsets:
            if not signalled and offset >= size * 0.9:
                raise RuntimeError('Upload già quasi completo: nessuna finestra utile per il test.')
            emit('progress', acknowledged=offset, size=size)
            if not signalled and offset >= threshold:
                signalled = True
                emit('cut_now', acknowledged=offset, size=size)
            if offset >= size * 0.9:
                return dict(outcome='no_cut_observed', acknowledged=offset)
    except Exception as exc:
        if not signalled:
            raise
        # A BLE timeout alone is not proof of a physical power cut.
        return dict(outcome='upload_interrupted_after_signal', acknowledged=offset,
                    error=repr(exc))
    return dict(outcome='no_cut_observed', acknowledged=offset)


async def read_state(client, recovery_hash=RECOVERY_HASH):
    from smpclient.generics import error
    from smpclient.requests.image_management import ImageStatesRead
    response = await client.request(ImageStatesRead())
    if error(response):
        raise RuntimeError(str(response))
    images = [dict(slot=i.slot, active=i.active, version=i.version,
                   hash=i.hash.hex()) for i in response.images]
    if not any(i['slot'] == 1 and i['active'] and i['hash'] == recovery_hash
               for i in images):
        raise RuntimeError(f'Recovery atteso non attivo: {images}')
    return images


async def run(args):
    from smpclient import SMPClient
    from smpclient.transport.ble import SMPBLETransport

    data = args.image.read_bytes()
    if hashlib.sha256(data).hexdigest() != args.image_sha256:
        raise RuntimeError('Il firmware locale non corrisponde alla build DK verificata.')
    folder = ROOT / 'experiments' / ('dk-manual-power-cut-' +
                                   datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    folder.mkdir(parents=True)
    log = folder / 'events.jsonl'

    def emit(event, **fields):
        with log.open('a') as file:
            file.write(json.dumps(dict(time=datetime.now(timezone.utc).isoformat(),
                                       event=event, **fields)) + '\n')
        if event == 'progress':
            print(f"\rUpload: {fields['acknowledged']}/{fields['size']} byte", end='', flush=True)
        elif event == 'cut_now':
            print('\n\a\033[1;31m>>> STACCA ORA LA USB DEL DK <<<\033[0m\n'
                  'Lascia il DK spento. Il trasferimento continua finché perde il collegamento.',
                  flush=True)

    async def prompt(message):
        return (await asyncio.to_thread(input, '\n' + message)).strip().lower()

    print('Prova SOLO sul DK; lascia il Vimar scollegato.\n'
          'Il test sovrascrive parzialmente l’app principale. Dopo servirà ripristinarla via BLE.\n'
          'Prepara la mano sul cavo: al segnale staccalo e verifica che il DK si spenga.\n'
          'Ora entra nel recupero con B1 + RESET, poi rilascia B1.\n'
          'Premi Invio quando sei pronto; Ctrl+C annulla.\n'
          f'Log: {log}', flush=True)
    await prompt('Invio per iniziare: ')
    emit('start', address=args.address, image=str(args.image), sha256=args.image_sha256,
         signal_at=args.signal_at, netbuf=2475)
    transport = SMPBLETransport()
    async with SMPClient(transport, args.address, timeout_s=20) as client:
        emit('initial_recovery_verified', images=await read_state(client, args.recovery_hash))
        # Capacity pinned to the exact recovery image hash checked above.
        transport.initialize(2475)
        generator = client.upload(data, first_timeout_s=60)
        try:
            result = await cut_window(generator, len(data), args.signal_at, emit)
        finally:
            await generator.aclose()
        emit('upload_result', **result)
    print('\nTrasferimento terminato.', flush=True)
    if result['outcome'] != 'upload_interrupted_after_signal':
        print('Taglio durante upload non rilevato: prova NON validata. Non staccare ora la USB.')
        return 2
    answer = await prompt('Hai staccato al segnale e visto il DK completamente spento? Scrivi SI: ')
    emit('operator_power_loss_confirmation', confirmed=answer == 'si')
    if answer != 'si':
        print('Perdita di alimentazione non confermata: prova NON validata.')
        return 2
    await prompt('Ricollega la USB SENZA premere B1: verifichiamo il recupero automatico. Poi Invio: ')
    # No boot gesture/reset command here: the test is automatic fallback after power loss.
    async with SMPClient(SMPBLETransport(), args.address, timeout_s=45) as client:
        images = await read_state(client, args.recovery_hash)
        emit('automatic_recovery_verified', images=images)
    print(f'Recupero BLE automatico verificato dopo il taglio dichiarato.\nLog: {log}\n'
          'Il DK resta in recupero: l’app principale deve essere ripristinata.\n'
          'Questo test non prova che il taglio sia caduto esattamente durante una scrittura flash.')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--address', required=True, help='Indirizzo BLE esatto del DK isolato')
    parser.add_argument('--image', type=Path, required=True, help='Immagine MAIN firmata per il DK di prova')
    parser.add_argument('--image-sha256', required=True, help='SHA-256 atteso dell’intero file MAIN')
    parser.add_argument('--recovery-hash', required=True, help='Hash SMP atteso della recovery attiva')
    parser.add_argument('--signal-at', type=int, default=65536,
                        help='Byte confermati prima del segnale (default: 65536).')
    args = parser.parse_args()
    import re
    for name in ('image_sha256', 'recovery_hash'):
        if not re.fullmatch(r'[0-9a-f]{64}', getattr(args, name)):
            parser.error('--' + name.replace('_', '-') + ' richiede64 cifre esadecimali minuscole')
    if not 4096 <= args.signal_at <= 262144:
        parser.error('--signal-at deve essere tra 4096 e 262144')
    if not sys.stdin.isatty():
        parser.error('Avvia lo script in un terminale interattivo.')
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print('\nAnnullato. Nessun ripristino/reset automatico; il DK potrebbe richiedere recupero BLE.')
        return 130
    except Exception as exc:
        print(f'Prova NON validata: {exc}\nIl DK potrebbe richiedere recupero BLE.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
