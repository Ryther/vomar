"""Decode saved allocation-refusal records. No network, upload, reset or flash access."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import struct
import zlib
from tools.firmware.read_fault_diagnostics import resolve_callbacks

MASK = 0xffffffff


def blob(state, name, size):
    value = state.get(name)
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-fA-F]{' + str(size * 2) + '}', value):
        raise ValueError('Missing or malformed ' + name)
    return bytes.fromhex(value)


def decode_record(data):
    if not isinstance(data, bytes) or len(data) != 48:
        raise ValueError('Expected48-byte allocation record')
    if data == bytes(48):
        return None
    sequence, time, caller, requested = struct.unpack_from('<IIII', data)
    bitmap = int.from_bytes(data[16:21], 'little')
    flags, units, out, incoming, queued, pool_size, valid = data[21:28]
    head, tail, oldest, age = struct.unpack_from('<IIII', data, 28)
    if flags & ~31 or valid & ~63 or data[46:48] != bytes(2) or flags & 8 and not flags & 4:
        raise ValueError('Invalid allocation record flags')
    if flags & 12 and not flags & 2:
        raise ValueError('Storage flags without caller context')
    if flags & 4 and not flags & 8:
        raise ValueError('Inconsistent successful storage result in refusal')
    if valid & 1 and queued > 32 or valid & 2 and not 1 <= pool_size <= 40:
        raise ValueError('Invalid allocation snapshot bounds')
    if valid & 2 and bitmap >> pool_size:
        raise ValueError('Allocation bitmap exceeds pool')
    path = 'unattributed'
    if flags & 2:
        path = 'storage_refused' if flags & 4 else 'quota_before_storage'
    return dict(sequence=sequence, time_ms=time, time_exact=not bool(flags & 16),
                holder_coverage_complete=not bool(valid & 32), caller=caller if flags & 2 else None,
                raw_caller=caller, direction=('IN' if flags & 1 else 'OUT') if flags & 2 else None,
                requested_bytes=requested if flags & 2 else None,
                storage_units=units if flags & 4 else None, allocation_path=path,
                out=out, incoming=incoming, pool_size=pool_size,
                bitmap=data[16:21].hex(), occupied_units=bitmap.bit_count() if valid & 2 else None,
                queue=dict(used=queued, valid=bool(valid & 1),
                           head_callback=head if valid & 1 and queued else None,
                           tail_callback=tail if valid & 1 and queued else None),
                oldest_holder=dict(id=data[44], units=data[45],
                                   caller=oldest if valid & 8 else None,
                                   age_ms=age if valid & 4 else None,
                                   age_exact=bool(valid & 4) and not bool(flags & 16 or valid & 16),
                                   raw_caller=oldest, raw_age_ms=age),
                flags=flags, valid=valid)


def decode_previous(state):
    names = ['allocation_trace_previous_' + str(i) for i in range(3)]
    status = state.get('allocation_trace_retained_status', 0)
    if type(status) is not int or not 0 <= status <= MASK:
        raise ValueError('Invalid retained status')
    if not any(name in state for name in names) and not status & 2:
        return None
    missing = [name for name in names if name not in state]
    if missing:
        return dict(complete=False, missing_attributes=missing)
    raw = b''.join(blob(state, name, 32) for name in names)
    if raw == bytes(96):
        if status & 2:
            raise ValueError('Previous commit flag without retained record')
        return None
    magic, version, generation, boot = struct.unpack_from('<IIII', raw)
    crc, commit = struct.unpack_from('<II', raw, 80)
    if (magic != 0x414c4c43 or version != 1 or commit != 0x41545243
            or crc != zlib.crc32(raw[:80]) or raw[88:] != bytes(8)):
        raise ValueError('Invalid previous allocation commit or CRC')
    record = decode_record(raw[32:80])
    if record is None:
        raise ValueError('Empty previous allocation record')
    return dict(complete=True, generation=generation, boot_sequence=boot,
                build_id=raw[16:32].hex(), record=record,
                interpretation='Previous committed SRAM evidence; may precede uncommitted newer events.')


def decode_capture(state):
    if not isinstance(state, dict):
        raise ValueError('Expected allocation capture object')
    build = state.get('firmware_build_id')
    boot = state.get('boot_sequence')
    if not isinstance(build, str) or not re.fullmatch('[0-9a-fA-F]{32}', build):
        raise ValueError('Missing diagnostic build identity')
    if type(boot) is not int or not 0 <= boot <= MASK:
        raise ValueError('Missing valid boot sequence')
    if 'boot_sequence_after' in state and state['boot_sequence_after'] != boot:
        raise ValueError('Mixed boot samples')
    version, size, capacity, count_flags, total, overwritten, unknown, holder_sequence = struct.unpack(
        '<BBBBIIII', blob(state, 'allocation_trace_metadata', 20))
    if version == 2:
        if any((size, capacity, count_flags, total, overwritten, unknown, holder_sequence)):
            raise ValueError('Invalid disabled allocation profile')
        return dict(current=dict(build_id=build.lower(), boot_sequence=boot,
            available=False, metadata=dict(format=2, total=0), first=None,
            latest=None, history=[], holders=[], complete='boot_sequence_after' in state,
            attribution_complete=False, missing_attributes=[]), previous=None,
            interpretation='Allocation history is not compiled into this production profile.')
    count = count_flags & 63
    wrapped, history_overwritten = bool(count_flags & 64), bool(count_flags & 128)
    if (version, size, capacity) != (1, 48, 32) or count > 32 or holder_sequence != total:
        raise ValueError('Invalid allocation metadata')
    if wrapped:
        if count != 32 or not history_overwritten or (overwritten + 32) & MASK != total:
            raise ValueError('Inconsistent wrapped allocation metadata')
    elif (count != min(total, 32) or overwritten != max(total - 32, 0)
          or history_overwritten != (total > 32)):
        raise ValueError('Inconsistent allocation metadata counts')
    metadata = dict(format=version, record_bytes=size, capacity=capacity, retained=count,
                    total=total, overwritten=overwritten, missing_context=unknown,
                    holder_sequence=holder_sequence, counter_wrapped=wrapped,
                    history_overwritten=history_overwritten)
    missing = []
    current = dict(build_id=build.lower(), boot_sequence=boot, metadata=metadata)
    for key in ('allocation_trace_dropped', 'allocation_trace_lifetime_gaps'):
        if key not in state:
            missing.append(key)
            current[key] = None
        elif type(state[key]) is not int or not 0 <= state[key] <= MASK:
            raise ValueError('Invalid ' + key)
        else:
            current[key] = state[key]
    for kind in ('first', 'latest'):
        name = 'allocation_trace_' + kind
        current[kind] = decode_record(blob(state, name, 48)) if name in state else None
        if count and current[kind] is None:
            missing.append(name)
    if current['latest'] is not None and current['latest']['sequence'] != total:
        raise ValueError('Mixed latest allocation history')
    if current['first'] is not None and current['first']['sequence'] != 1:
        raise ValueError('Invalid first allocation sequence')
    if not wrapped and total == 1 and current['first'] and current['latest']:
        if blob(state, 'allocation_trace_first', 48) != blob(state, 'allocation_trace_latest', 48):
            raise ValueError('Conflicting first/latest allocation records')
    history = []
    needed = {(total - age - 1) % 32 for age in range(count)}
    for index in range(32):
        name = 'allocation_trace_history_' + str(index)
        if name not in state:
            if index in needed:
                missing.append(name)
            continue
        record = decode_record(blob(state, name, 48))
        if record is None:
            if index in needed:
                missing.append(name)
            continue
        if (record['sequence'] - 1) % 32 != index or (total - record['sequence']) & MASK >= count:
            raise ValueError('Mixed allocation history slots')
        if current['latest'] and record['sequence'] == total:
            if blob(state, name, 48) != blob(state, 'allocation_trace_latest', 48):
                raise ValueError('Conflicting latest allocation history record')
        if not wrapped and record['sequence'] == 1 and current['first']:
            if blob(state, name, 48) != blob(state, 'allocation_trace_first', 48):
                raise ValueError('Conflicting first allocation history record')
        history.append(record)
    current['history'] = sorted(history, key=lambda r: (total - r['sequence']) & MASK, reverse=True)
    holders = []
    for index in range(14):
        name = 'allocation_trace_holders_' + str(index)
        if name not in state:
            if count:
                missing.append(name)
            continue
        raw = blob(state, name, 40)
        if struct.unpack_from('<I', raw)[0] != holder_sequence:
            raise ValueError('Mixed allocation holder snapshot')
        for slot in range(3):
            pc, age, identifier, units, direction, flags = struct.unpack_from('<IIBBBB', raw, 4 + 12 * slot)
            if not flags and not identifier:
                continue
            if (index * 3 + slot >= 40 or identifier != index * 3 + slot + 1
                    or flags & ~15 or not flags & 1 or not 1 <= units <= 41 - identifier
                    or direction not in ((0, 1) if flags & 2 else (255,))):
                raise ValueError('Invalid allocation holder record')
            holders.append(dict(id=identifier, units=units, age_ms=age,
                                direction=('IN' if direction else 'OUT') if flags & 2 else None,
                                caller=pc if flags & 2 else None,
                                age_exact=not bool(flags & 4) and bool(current['latest'] and current['latest']['time_exact']),
                                coverage_complete=not bool(flags & 8), flags=flags))
    current.update(holders=holders, missing_attributes=missing,
                   complete=not missing and 'boot_sequence_after' in state)
    current['attribution_complete'] = (current['complete'] and unknown == 0
        and current['allocation_trace_dropped'] == 0 and current['allocation_trace_lifetime_gaps'] == 0
        and all(r['caller'] is not None and r['holder_coverage_complete']
                and (not r['oldest_holder']['id'] or r['oldest_holder']['caller'] is not None) for r in history)
        and all(h['caller'] is not None and h['coverage_complete'] for h in holders))
    return dict(current=current, previous=decode_previous(state),
                interpretation='Observed allocation path and state; physical cause and freeze correction are not established.')


def resolve_record(record, build_id, elf_path):
    def call_site(address):
        return (address & ~1) - 2 if address is not None and address > 2 else None
    origin = resolve_callbacks(dict(build_id=build_id, queue=dict(
        head_callback=call_site(record['caller']),
        tail_callback=call_site(record['oldest_holder']['caller']))), elf_path)
    queue = resolve_callbacks(dict(build_id=build_id, queue=record['queue']), elf_path)
    return dict(elf_sha256=origin['elf_sha256'], caller=origin['callbacks']['head_callback'],
                oldest_holder=origin['callbacks']['tail_callback'], queue=queue['callbacks'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--elf', type=Path, action='append', default=[])
    args = parser.parse_args()
    try:
        if args.capture.stat().st_size > 512 * 1024:
            raise ValueError('Capture exceeds512KiB')
        result = decode_capture(json.loads(args.capture.read_text()))
        current = result['current']
        previous = result['previous']
        groups = [(current['build_id'], [r for r in
                  [current['first'], current['latest'], *current['history']] if r is not None])]
        if previous and previous['complete']:
            groups.append((previous['build_id'], [previous['record']]))
        for path in args.elf:
            matched = False
            for build, records in groups:
                try:
                    resolve_callbacks(dict(build_id=build, queue={}), path)
                except ValueError as error:
                    if 'identity' in str(error):
                        continue
                    raise
                matched = True
                for record in records:
                    record['symbol_resolution'] = resolve_record(record, build, path)
            if not matched:
                raise ValueError('ELF build identity does not match captured records')
        print(json.dumps(result, indent=2))
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
