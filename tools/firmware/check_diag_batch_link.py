"""Read-only link admission for counted diagnostics and existing ownership hooks."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import sys

from elftools.elf.elffile import ELFFile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_ownership_link import inspect as ownership_inspect
from prepare_diag_batch_sdk import (ARCHIVE_SHA, EXPORTED, RAM_CHECKPOINT, GETTER, REAL_GETTER,
                                    ALLOCATION_ENTRIES)
from prepare_compact_sdk import KIND as COMPACT_KIND, verify_report as verify_compact_report


def inspect(path: Path, *, require_profile: bool = False) -> dict:
    ownership = ownership_inspect(path)
    raw = path.read_bytes()
    elf = ELFFile(io.BytesIO(raw))
    definitions = {s.name: s for s in elf.get_section_by_name('.symtab').iter_symbols()
                   if s['st_shndx'] != 'SHN_UNDEF'}
    functions = [(s['st_value'] & ~1, (s['st_value'] & ~1) + s['st_size'], s.name)
                 for s in definitions.values() if s['st_info']['type'] == 'STT_FUNC' and s['st_size']]
    references = []
    allocation_symbols = set(ALLOCATION_ENTRIES) | set(ALLOCATION_ENTRIES.values())
    for section in elf.iter_sections():
        if section['sh_type'] not in ('SHT_REL', 'SHT_RELA'):
            continue
        target = elf.get_section(section['sh_info'])
        if not target['sh_flags'] & 2:
            continue
        table = elf.get_section(section['sh_link'])
        for row in section.iter_relocations():
            name = table.get_symbol(row['r_info_sym']).name
            if name not in allocation_symbols | {EXPORTED, '__wrap_zb_schedule_callback', 'zb_schedule_callback',
                            'vimar_diag_batch_schedule', 'vimar_diag_batch_deliver', 'zdo_diagnostics_inc',
                            'zb_timer_get', 'zb_schedule_alarm', '__wrap_zb_osif_abort',
                            RAM_CHECKPOINT, 'zb_nvram_write_dataset', GETTER, REAL_GETTER,
                            'vimar_alloc_trace_failure', 'vimar_alloc_trace_storage_result',
                            'vimar_alloc_trace_release', 'vimar_alloc_trace_pool_reset'}:
                continue
            origin = next((n for lo, hi, n in functions if lo <= row['r_offset'] < hi), target.name)
            references.append(dict(origin=origin, target=name, address=hex(row['r_offset']),
                                   type=row['r_info_type']))

    def edge(origin, target):
        return any(r['origin'] == origin and r['target'] == target for r in references)

    def data(name):
        symbol = definitions.get(name)
        if symbol is None or not isinstance(symbol['st_shndx'], int):
            return b''
        section = elf.get_section(symbol['st_shndx'])
        offset = (symbol['st_value'] & ~1 if symbol['st_info']['type'] == 'STT_FUNC'
                  else symbol['st_value']) - section['sh_addr']
        return section.data()[offset:offset + symbol['st_size']]

    callback = definitions.get(EXPORTED)
    getter, real_getter = definitions.get(GETTER), definitions.get(REAL_GETTER)
    capture_sites = [int(r['address'], 16) for r in references
                     if r['origin'] == '__wrap_zb_schedule_callback' and r['target'] == 'vimar_alloc_trace_failure']
    batch_sites = [int(r['address'], 16) for r in references
                   if r['origin'] == '__wrap_zb_schedule_callback' and r['target'] == 'vimar_diag_batch_schedule']
    getter_bypasses = [r for r in references if r['target'] == REAL_GETTER and r['origin'] != GETTER]
    allocation_bypasses = [r for r in references for name, real in ALLOCATION_ENTRIES.items()
                           if r['target'] == real and r['origin'] != name]
    allocation_seams = []
    for name, real in ALLOCATION_ENTRIES.items():
        public, native = definitions.get(name), definitions.get(real)
        allocation_seams.append(bool(public and native
            and public['st_info']['bind'] == native['st_info']['bind'] == 'STB_GLOBAL'
            and public['st_value'] != native['st_value'] and edge(name, real)))
    trace_profile = data('vimar_alloc_trace_enabled')
    capacity = data('gc_sched_q_size')
    queue = definitions.get('gc_cb_q')
    checks = dict(
        ownership_passed=ownership['passed'],
        ownership_uses_same_image=ownership['sha256'] == hashlib.sha256(raw).hexdigest(),
        exported_original_callback=bool(callback and callback['st_info']['bind'] == 'STB_GLOBAL'
                                        and callback['st_size'] == 6 and data(EXPORTED)[:2] == b'\x13\x20'),
        allocation_diagnostic_intercepted=edge(REAL_GETTER, EXPORTED)
                                          and edge(REAL_GETTER, '__wrap_zb_schedule_callback')
                                          and not edge(REAL_GETTER, 'zb_schedule_callback'),
        native_getter_interposition=bool(getter and real_getter
                                        and getter['st_info']['bind'] == 'STB_GLOBAL'
                                        and real_getter['st_info']['bind'] == 'STB_GLOBAL'
                                        and getter['st_value'] != real_getter['st_value']
                                        and edge(GETTER, REAL_GETTER)),
        no_native_getter_bypass=not getter_bypasses,
        all_allocation_entries_interposed=all(allocation_seams),
        no_allocation_entry_bypass=not allocation_bypasses,
        delayed_consumers_intercepted=edge('zb_get_buf_delayed', 'process_delayed_buf_entry_unsafe')
                                      and edge('zb_buf_free_func', 'process_delayed_buf_entry_unsafe'),
        internal_getters_intercepted=edge('zb_buf_get_out_func', GETTER)
                                     and edge('zb_buf_get_any_func', GETTER),
        failure_capture_precedes_batch=bool(capture_sites and batch_sites
                                           and max(capture_sites) < min(batch_sites)),
        storage_lifetime_observed=edge('__wrap_zb_bufpool_storage_allocate', 'vimar_alloc_trace_storage_result')
                                  and edge('__wrap_zb_bufpool_storage_free', 'vimar_alloc_trace_release')
                                  and edge('__wrap_zb_bufpool_storage_init', 'vimar_alloc_trace_pool_reset'),
        wrapper_routes_batch=edge('__wrap_zb_schedule_callback', EXPORTED)
                              and edge('__wrap_zb_schedule_callback', 'vimar_diag_batch_schedule'),
        batch_uses_native_queue=edge('vimar_diag_batch_schedule', 'vimar_diag_batch_deliver')
                                and edge('vimar_diag_batch_schedule', 'zb_schedule_callback'),
        delivery_uses_original_callback=edge('vimar_diag_batch_deliver', EXPORTED),
        delivery_uses_native_cooldown=edge('vimar_diag_batch_deliver', 'zb_timer_get')
                                     and edge('vimar_diag_batch_deliver', 'zb_schedule_alarm'),
        batch_has_unconditional_error_paths=edge('vimar_diag_batch_schedule', '__wrap_zb_osif_abort')
                                            and edge('vimar_diag_batch_deliver', '__wrap_zb_osif_abort'),
        original_counter_algorithm=edge(EXPORTED, 'zdo_diagnostics_inc'),
        statistics_use_volatile_checkpoint=edge('zdo_diagnostics_inc', RAM_CHECKPOINT)
                                           and not edge('zdo_diagnostics_inc', 'zb_nvram_write_dataset'),
        checkpoint_rejects_unexpected_dataset=edge(RAM_CHECKPOINT, '__wrap_zb_osif_abort'),
        queue_capacity_unchanged=bool(len(capacity) == 4 and struct.unpack('<I', capacity)[0] == 32
                                     and queue and queue['st_size'] == 236),
    )
    if require_profile:
        checks['allocation_profile_marker_present'] = bool(trace_profile)
    if trace_profile:
        checks['allocation_profile_valid'] = trace_profile in (bytes(4), b'\x01\x00\x00\x00')
        if trace_profile == bytes(4):
            checks['allocation_capture_storage_absent'] = not any(name in definitions for name in (
                'vimar_alloc_trace_first', 'vimar_alloc_trace_latest',
                'vimar_alloc_trace_history', 'vimar_alloc_trace_holders',
                'vimar_alloc_trace_previous', 'retain_failure'))
            checks['allocation_disabled_metadata'] = data('vimar_alloc_trace_metadata') == bytes([20, 2]) + bytes(19)
    enabled = trace_profile != bytes(4)
    return dict(elf=str(path.resolve()), sha256=hashlib.sha256(raw).hexdigest(),
                checks=checks, passed=all(checks.values()), references=references,
                allocation_trace_enabled=enabled,
                getterBypasses=getter_bypasses, hardwareQualified=False,
                allocationBypasses=allocation_bypasses,
                scope='Native link admission; not runtime or physical qualification')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('elf', type=Path)
    parser.add_argument('--sdk-report', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ar', type=Path)
    args = parser.parse_args()
    report = inspect(args.elf, require_profile=True)
    sdk = json.loads(args.sdk_report.read_text())
    if sdk.get('kind') == COMPACT_KIND:
        try:
            report['checks']['reviewed_derived_sdk'] = bool(args.ar and verify_compact_report(sdk, args.ar))
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            report['checks']['reviewed_derived_sdk'] = False
            report['sdkAdmissionError'] = str(exc)
    else:
        report['checks']['reviewed_derived_sdk'] = (
            sdk['source_sha256'] == ARCHIVE_SHA
            and hashlib.sha256(Path(sdk['source']).read_bytes()).hexdigest() == ARCHIVE_SHA
            and sdk['allocated_sections_unchanged'] and sdk['normalized_relocations_unchanged']
            and sdk['native_getter_interposed'] and sdk['real_getter'] == REAL_GETTER
            and sdk['allocation_entries'] == ALLOCATION_ENTRIES
            and sdk['volatile_statistics']['allocated_sections_unchanged']
            and sdk['volatile_statistics']['normalized_relocations_unchanged']
            and sdk['volatile_statistics']['dataset'] == 31
            and sdk['volatile_statistics']['redirected_calls'] == 1
            and sdk['volatile_statistics']['policy_symbol'] == RAM_CHECKPOINT
            and hashlib.sha256(Path(sdk['archive']).read_bytes()).hexdigest() == sdk['archive_sha256'])
    report['passed'] = all(report['checks'].values())
    report['sdkArchiveSha256'] = sdk['archive_sha256']
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(passed=report['passed'], checks=report['checks'])))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
