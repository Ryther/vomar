"""Gate real synthetic ARM relocation graphs; no ARM instructions execute."""
from pathlib import Path
import subprocess

import pytest

from tools.firmware import check_diag_batch_link as audit
from tools.firmware.prepare_diag_batch_sdk import ALLOCATION_ENTRIES
from tools.firmware.tests.test_ownership_link_audit import crosscompiler, synthetic_elf


def graph(directory, compiler, *, bypass=False, cooldown=True, abort_guard=True, volatile=True,
          real_bypass=False, late_capture=False, delayed_bypass=False):
    synthetic_elf(directory, compiler)
    source = directory / 'graph.S'
    text = source.read_text()
    text = text.replace('__wrap_zb_schedule_callback:\nb zb_schedule_callback',
                        '__wrap_zb_schedule_callback:\n' +
                        ('bl vimar_diag_batch_schedule\nbl vimar_alloc_trace_failure\n' if late_capture else
                         'bl vimar_alloc_trace_failure\nbl vimar_diag_batch_schedule\n') +
                        'ldr r2, 9f\nb zb_schedule_callback\n.balign 4\n'
                        '9: .word vimar_sdk_buf_diag_handle_alloc_failure')
    functions = {
        'zb_buf_get_func': ['b vimar_sdk_buf_get_func'],
        'zb_buf_get_out_func': ['b ' + ('vimar_sdk_buf_get_func' if real_bypass else 'zb_buf_get_func')],
        'zb_buf_get_any_func': ['b zb_buf_get_func'],
        'vimar_sdk_buf_get_func': ['ldr r0, 8f', 'b ' + ('zb_schedule_callback' if bypass else '__wrap_zb_schedule_callback'),
                           '.balign 4', '8: .word vimar_sdk_buf_diag_handle_alloc_failure'],
        'vimar_diag_batch_schedule': ((['bl __wrap_zb_osif_abort'] if abort_guard else [])
                                     + ['ldr r0, 7f', 'b zb_schedule_callback', '.balign 4',
                                        '7: .word vimar_diag_batch_deliver']),
        'vimar_diag_batch_deliver': ((['bl zb_timer_get', 'bl zb_schedule_alarm'] if cooldown else [])
                                    + (['bl __wrap_zb_osif_abort'] if abort_guard else [])
                                    + ['b vimar_sdk_buf_diag_handle_alloc_failure']),
        'zb_timer_get': ['bx lr'],
        'zb_schedule_alarm': ['bx lr'],
        '__wrap_zb_osif_abort': ['bx lr'],
        'vimar_sdk_buf_diag_handle_alloc_failure': ['movs r0,#19', 'b.w zdo_diagnostics_inc'],
        'zdo_diagnostics_inc': ['b vimar_diag_statistics_checkpoint' if volatile else 'b zb_nvram_write_dataset'],
        'vimar_diag_statistics_checkpoint': ['b __wrap_zb_osif_abort'],
        'zb_nvram_write_dataset': ['bx lr'],
        'vimar_alloc_trace_failure': ['bx lr'],
        'vimar_alloc_trace_storage_result': ['bx lr'],
        'vimar_alloc_trace_release': ['bx lr'],
        'vimar_alloc_trace_pool_reset': ['bx lr'],
    }
    for native, real in ALLOCATION_ENTRIES.items():
        if native == 'zb_buf_get_func':
            continue
        functions[native] = ['b ' + real]
        functions[real] = ['bx lr']
    target = ('vimar_sdk_process_delayed_buf_entry_unsafe' if delayed_bypass else
              'process_delayed_buf_entry_unsafe')
    functions['zb_get_buf_delayed'] = ['b ' + target]
    text = text.replace('zb_buf_free_func:\n',
                        'zb_buf_free_func:\nbl process_delayed_buf_entry_unsafe\n')
    for origin, target in [('__wrap_zb_bufpool_storage_allocate','vimar_alloc_trace_storage_result'),
                           ('__wrap_zb_bufpool_storage_free','vimar_alloc_trace_release'),
                           ('__wrap_zb_bufpool_storage_init','vimar_alloc_trace_pool_reset')]:
        text = text.replace(origin+':\n',origin+':\nbl '+target+'\n')
    for name, body in functions.items():
        text += f'\n.global {name}\n.type {name}, %function\n.thumb_func\n{name}:\n'
        text += '\n'.join(body) + f'\n.size {name}, .-{name}\n'
    text += '\n.data\n.global gc_sched_q_size\n.type gc_sched_q_size,%object\ngc_sched_q_size:\n.word 32\n.size gc_sched_q_size,4\n'
    text += '.bss\n.global gc_cb_q\n.type gc_cb_q,%object\ngc_cb_q:\n.space 236\n.size gc_cb_q,236\n'
    source.write_text(text)
    target = directory / 'diag.elf'
    subprocess.run([str(compiler), '-mcpu=cortex-m4', '-mthumb', '-nostdlib',
                    '-Wl,--emit-relocs', '-Wl,-e,aps_producer', str(source), '-o', str(target)],
                   check=True, capture_output=True, text=True)
    return target


def test_complete_diagnostic_graph_passes(tmp_path, crosscompiler):
    report = audit.inspect(graph(tmp_path, crosscompiler))
    assert report['passed'] and all(report['checks'].values())
    assert report['hardwareQualified'] is False


def test_internal_native_getter_bypass_rejected(tmp_path, crosscompiler):
    report = audit.inspect(graph(tmp_path, crosscompiler, real_bypass=True))
    assert report['checks'].get('no_native_getter_bypass', True) is False


def test_delayed_consumer_cannot_bypass_requester_context(tmp_path, crosscompiler):
    report = audit.inspect(graph(tmp_path, crosscompiler, delayed_bypass=True))
    assert report['checks'].get('delayed_consumers_intercepted', True) is False
    assert report['checks'].get('no_allocation_entry_bypass', True) is False


def test_capture_after_diagnostic_admission_rejected(tmp_path, crosscompiler):
    report = audit.inspect(graph(tmp_path, crosscompiler, late_capture=True))
    assert report['checks'].get('failure_capture_precedes_batch', True) is False


def test_original_ownership_graph_is_insufficient(tmp_path, crosscompiler):
    report = audit.inspect(synthetic_elf(tmp_path, crosscompiler))
    assert not report['passed']
    assert report['checks']['ownership_passed']
    assert not report['checks']['allocation_diagnostic_intercepted']


def test_native_getter_bypass_rejected(tmp_path, crosscompiler):
    report = audit.inspect(graph(tmp_path, crosscompiler, bypass=True))
    assert not report['passed']
    assert not report['checks']['allocation_diagnostic_intercepted']


def test_unbounded_batch_delivery_rejected(tmp_path, crosscompiler):
    report = audit.inspect(graph(tmp_path, crosscompiler, cooldown=False))
    assert not report['passed']


def test_optional_assertions_cannot_replace_abort_guards(tmp_path, crosscompiler):
    report = audit.inspect(graph(tmp_path, crosscompiler, abort_guard=False))
    assert not report['passed']


def test_replaced_input_cannot_mix_ownership_and_batch_evidence(tmp_path, crosscompiler, monkeypatch):
    target = graph(tmp_path, crosscompiler)
    original = audit.ownership_inspect

    def different_snapshot(path):
        result = original(path)
        result['sha256'] = '0' * 64
        return result

    monkeypatch.setattr(audit, 'ownership_inspect', different_snapshot)
    report = audit.inspect(target)
    assert not report['passed'] and not report['checks']['ownership_uses_same_image']


def test_original_diagnostic_flash_path_rejected(tmp_path, crosscompiler):
    report = audit.inspect(graph(tmp_path, crosscompiler, volatile=False))
    assert not report['passed']
    assert not report['checks']['statistics_use_volatile_checkpoint']
