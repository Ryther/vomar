#!/usr/bin/env python3
"""Authenticated BLE client for our research firmware (not the stock Vimar protocol)."""
import argparse
import asyncio
import json
import secrets
import struct

SERVICE = 'fde30805-c001-4a40-8d00-308050000001'
COMMAND = 'fde30805-c001-4a40-8d00-308050000002'


def encode(opcode, sequence, argument=0):
    if opcode == 1 and not -32768 <= argument <= 32767:
        raise ValueError('Il livello deve essere tra -32768 e 32767.')
    return struct.pack('<BBHi', 1, opcode, sequence, argument)


def decode(data, opcode, sequence):
    if len(data) != 20:
        raise ValueError('Risposta diagnostica di lunghezza errata.')
    version, operation, seq, status, level, uptime, flags = struct.unpack('<BBHiiII', data)
    if (version, operation, seq) != (1, opcode, sequence):
        raise ValueError('Versione/comando/sequenza non corrispondenti.')
    result = dict(status=status, level=level, uptime_ms=uptime, capabilities=flags,
                  simulated=bool(flags & 1), software_recovery=bool(flags & 2),
                  stock_output_enabled=bool(flags & 4), output_fault=bool(flags & 8))
    if status != 0:
        raise RuntimeError(f'Comando rifiutato: {result}')
    return result


async def run(args):
    from bleak import BleakClient
    operations = {'status': (0, 0), 'level': (1, args.value), 'off': (1, -32768),
                  'on': (1, 32767), 'recovery': (2, 0)}
    opcode, argument = operations[args.command]
    sequence = secrets.randbelow(65536)
    request = encode(opcode, sequence, argument)
    # Existing BlueZ bond is reused. Pairing failures are surfaced; this client
    # never removes bonds, registers a global agent or changes controller state.
    async with BleakClient(args.address, timeout=30) as client:
        if client.services.get_service(SERVICE) is None:
            raise RuntimeError('Il dispositivo non espone la nostra console di ricerca.')
        await client.write_gatt_char(COMMAND, request, response=True)
        result = decode(bytes(await client.read_gatt_char(COMMAND)), opcode, sequence)
        print(json.dumps(result, indent=2))
        if result['simulated']:
            print('Backend simulato: nessun comando alla luce è stato eseguito.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--address', default='@VIMAR_NORMAL_BLE_ADDRESS@')
    parser.add_argument('command', choices=('status', 'level', 'off', 'on', 'recovery'))
    parser.add_argument('value', nargs='?', type=int)
    args = parser.parse_args()
    if (args.command == 'level') != (args.value is not None):
        parser.error('Specifica un valore soltanto per il comando level.')
    try:
        asyncio.run(run(args))
    except (RuntimeError, ValueError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
