"""Audit authored synthetic ELF graphs; never execute ARM or vendor firmware."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys

import pytest

from tools.firmware import check_ownership_link as audit

ROOT = Path(__file__).resolve().parents[3]
COMPILERS = (
    Path('/home/vscode/.cache/vomar/zephyr-sdk-1.0.1/gnu/arm-zephyr-eabi/bin/arm-zephyr-eabi-gcc'),
    Path('/opt/zephyr-sdk-1.0.1/gnu/arm-zephyr-eabi/bin/arm-zephyr-eabi-gcc'),
)


@pytest.fixture(scope='module')
def crosscompiler():
    compiler = next((p for p in COMPILERS if p.is_file()), None)
    if compiler is None:
        pytest.skip('Pinned Zephyr ARM crosscompiler is unavailable')
    return compiler


def synthetic_elf(directory, compiler, *, bypass=None, missing=None, relocations=True):
    """Create real ARM function/relocation records with explicit authored edges."""
    functions = {hook: [] for hook in audit.HOOKS}
    functions.update({'__wrap_' + hook: [hook] for hook in audit.HOOKS
                      if hook != missing})
    functions.update({
        'allocate_buffer_unsafe': ['__wrap_zb_bufpool_storage_allocate'],
        'zb_buf_free_func': ['__wrap_zb_bufpool_storage_free'],
        'zb_init_buffers': ['__wrap_zb_bufpool_storage_init'],
        'zb_nlde_data_request': ['__wrap_zb_schedule_callback'],
        'aps_producer': ['__wrap_zb_nlde_data_request'],
        'zb_multimac_mcps_data_confirm_proxy':
            [] if missing == 'zb_nwk_handle_mcps_data_confirm' else
            ['__wrap_zb_nwk_handle_mcps_data_confirm'],
    })
    if bypass is not None:
        functions['vendor_bypass'] = [bypass]
    lines = ['.syntax unified', '.thumb', '.text']
    for name, targets in functions.items():
        lines += [f'.global {name}', f'.type {name}, %function', '.thumb_func',
                  f'{name}:']
        if name == 'zb_multimac_mcps_data_confirm_proxy' and targets:
            lines += ['ldr r0, 1f', 'bx lr', '.balign 4', f'1: .word {targets[0]}']
        else:
            lines += [f'b {targets[0]}'] if targets else ['bx lr']
        lines += [f'.size {name}, .-{name}']
    source, target = directory / 'graph.S', directory / 'graph.elf'
    source.write_text('\n'.join(lines) + '\n')
    command = [str(compiler), '-mcpu=cortex-m4', '-mthumb', '-nostdlib',
               '-Wl,--build-id=none', '-Wl,-e,aps_producer']
    if relocations:
        command.append('-Wl,--emit-relocs')
    subprocess.run([*command, str(source), '-o', str(target)], check=True,
                   capture_output=True, text=True)
    return target


def test_positive_graph_and_cli_report(tmp_path, crosscompiler):
    elf = synthetic_elf(tmp_path, crosscompiler)
    original = elf.read_bytes()
    report = audit.inspect(elf)
    assert report['passed'] and all(report['checks'].values())
    assert report['missingWrappers'] == []
    assert report['lifecycleOrProducerBypasses'] == []
    assert report['hardwareQualified'] is False
    assert any(edge['from'] == 'zb_multimac_mcps_data_confirm_proxy' and
               edge['to'] == '__wrap_zb_nwk_handle_mcps_data_confirm' and
               edge['type'] == 2  # R_ARM_ABS32: callback literal, not a direct call.
               for edge in report['references'])
    output = tmp_path / 'audit.json'
    result = subprocess.run([
        sys.executable, '-m', 'tools.firmware.check_ownership_link', str(elf),
        '--output', str(output),
    ], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text()) == report
    assert elf.read_bytes() == original


@pytest.mark.parametrize('hook', audit.HOOKS[:7])
def test_lifecycle_and_producer_bypass_rejected(tmp_path, crosscompiler, hook):
    report = audit.inspect(synthetic_elf(tmp_path, crosscompiler, bypass=hook))
    assert not report['passed']
    assert not report['checks']['no_lifecycle_or_producer_bypass']
    assert any(edge['from'] == 'vendor_bypass' and edge['to'] == hook
               for edge in report['lifecycleOrProducerBypasses'])
    assert report['checks']['all_wrappers_defined']


def test_missing_wrapper_rejected(tmp_path, crosscompiler):
    hook = 'zb_nwk_handle_mcps_data_confirm'
    report = audit.inspect(synthetic_elf(tmp_path, crosscompiler, missing=hook))
    assert not report['passed']
    assert report['missingWrappers'] == ['__wrap_' + hook]
    assert not report['checks']['all_wrappers_defined']


def test_failed_gate_writes_report_and_returns_failure(tmp_path, crosscompiler):
    elf = synthetic_elf(tmp_path, crosscompiler, bypass='zb_nlde_data_request')
    output = tmp_path / 'failed-audit.json'
    result = subprocess.run([
        sys.executable, '-m', 'tools.firmware.check_ownership_link', str(elf),
        '--output', str(output),
    ], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 1, result.stderr
    assert json.loads(output.read_text())['passed'] is False


def test_digest_identifies_opened_elf_during_atomic_replacement(
        tmp_path, crosscompiler, monkeypatch):
    good_directory, bad_directory = tmp_path / 'good', tmp_path / 'bad'
    good_directory.mkdir()
    bad_directory.mkdir()
    original = synthetic_elf(good_directory, crosscompiler)
    replacement = synthetic_elf(bad_directory, crosscompiler,
                                bypass='zb_nlde_data_request')
    original_bytes = original.read_bytes()
    replacement_bytes = replacement.read_bytes()
    assert original_bytes != replacement_bytes
    real_elf_reader = audit.ELFFile

    def replace_path_after_open(stream):
        replacement.replace(original)
        return real_elf_reader(stream)

    monkeypatch.setattr(audit, 'ELFFile', replace_path_after_open)
    report = audit.inspect(original)
    assert original.read_bytes() == replacement_bytes
    assert report['passed'], 'The already-open good ELF supplies the parsed graph'
    assert report['sha256'] == hashlib.sha256(original_bytes).hexdigest()


def test_absent_relocations_rejected(tmp_path, crosscompiler):
    elf = synthetic_elf(tmp_path, crosscompiler, relocations=False)
    with pytest.raises(ValueError, match='Allocated relocation records required'):
        audit.inspect(elf)


def test_wrong_architecture_rejected(tmp_path):
    compiler = shutil.which('cc')
    if compiler is None:
        pytest.skip('Host compiler is unavailable for the non-ARM ELF control')
    source, elf = tmp_path / 'host.c', tmp_path / 'host.elf'
    source.write_text('int main(void) { return 0; }\n')
    subprocess.run([compiler, str(source), '-o', str(elf)], check=True,
                   capture_output=True, text=True)
    with pytest.raises(ValueError, match='An ARM ELF is required'):
        audit.inspect(elf)
