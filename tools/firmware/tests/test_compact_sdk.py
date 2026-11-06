"""Compact SDK derivation stays bound to reviewed native code and vendor inputs."""
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import struct

import pytest
from elftools.elf.elffile import ELFFile

from local_inputs import local_input, sdk_root
from tools.firmware import prepare_compact_sdk as compact


def test_unknown_sdk_fails_before_output_or_compiler(tmp_path):
    source = tmp_path / 'unknown.a'
    source.write_bytes(b'synthetic unknown SDK')
    output = tmp_path / 'new.a'
    with pytest.raises(ValueError, match='production'):
        compact.prepare_archive(source, tmp_path / 'unused-trace', output,
                                Path('unused-ar'), Path('unused-objcopy'), Path('unused-cc'))
    assert source.read_bytes() == b'synthetic unknown SDK' and not output.exists()


@pytest.mark.parametrize('report', [{}, {'source': None, 'trace_source': '', 'archive': ''}])
def test_malformed_report_is_a_validation_error(report):
    with pytest.raises(ValueError, match='report'):
        compact.verify_report(report, Path('must-not-execute'))


@pytest.fixture(scope='module')
def derived(tmp_path_factory):
    sdk = local_input(sdk_root() / 'ncs-zigbee/lib/zboss')
    prefix = Path(os.environ.get('ZEPHYR_SDK_INSTALL_DIR', '/opt/zephyr-sdk')) / 'gnu/arm-zephyr-eabi/bin'
    ar = local_input(prefix / 'arm-zephyr-eabi-ar')
    objcopy = local_input(prefix / 'arm-zephyr-eabi-objcopy')
    cc = local_input(prefix / 'arm-zephyr-eabi-gcc')
    out = tmp_path_factory.mktemp('compact-sdk')
    report = compact.prepare_archive(sdk / 'lib/cortex-m4/hard-float/libzboss.a',
        sdk / 'trace/lib/cortex-m4/hard-float/libzboss.a', out / 'libzboss.a', ar, objcopy, cc)
    return report, ar, out


def test_real_pinned_derivation_preserves_every_other_member(derived):
    report, ar, _ = derived
    assert compact.verify_report(report, ar) is True
    assert report['kind'] == compact.KIND
    assert report['native_compilation_members'] == ['nwk_main.o', 'zb_scheduler.o']
    assert report['trace_members'] == ['zb_bufpool_mult.o', 'zb_bufpool_mult_storage.o', 'zdo_diagnostics.o']
    assert report['hardware_qualified'] is False


@pytest.mark.parametrize('native', [False, True])
def test_rehashed_tampering_cannot_authorize_a_member(derived, tmp_path, native):
    report, ar, _ = derived
    output = tmp_path / 'tampered.a'
    shutil.copy2(report['archive'], output)
    members = compact.read_members(ar, output)
    name = 'nwk_main.o' if native else next(name for name in members if name not in compact.BOUNDARIES)
    replacement = tmp_path / name
    replacement.write_bytes(b'corrupt synthetic replacement')
    subprocess.run([str(ar), 'rD', str(output), str(replacement)], check=True, capture_output=True)
    changed = {**report, 'archive': str(output),
               'archive_sha256': hashlib.sha256(output.read_bytes()).hexdigest()}
    with pytest.raises(ValueError, match='member|native'):
        compact.verify_report(changed, ar)


@pytest.mark.parametrize('name,symbol', [
    ('zb_bufpool_mult.o', 'zb_buf_free_func'),
    ('zdo_diagnostics.o', 'zdo_diagnostics_inc'),
])
def test_rehashed_symbol_only_tampering_is_rejected(derived, tmp_path, name, symbol):
    report, ar, _ = derived
    output = tmp_path / 'symbol-tampered.a'
    shutil.copy2(report['archive'], output)
    raw = bytearray(compact.read_members(ar, output)[name])
    table = ELFFile(io.BytesIO(raw)).get_section_by_name('.symtab')
    rows = [(index, row) for index, row in enumerate(table.iter_symbols()) if row.name == symbol]
    assert len(rows) == 1
    index, row = rows[0]
    struct.pack_into('<I', raw, table['sh_offset'] + index * table['sh_entsize'] + 4,
                     row['st_value'] + 2)
    replacement = tmp_path / name
    replacement.write_bytes(raw)
    subprocess.run([str(ar), 'rDs', str(output), str(replacement)], check=True, capture_output=True)
    changed = {**report, 'archive': str(output),
               'archive_sha256': hashlib.sha256(output.read_bytes()).hexdigest()}
    with pytest.raises(ValueError, match='member'):
        compact.verify_report(changed, ar)
