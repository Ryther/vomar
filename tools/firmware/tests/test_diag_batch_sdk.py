"""Synthetic ARM objects verify symbol-only transformation without vendor input."""
from pathlib import Path
import hashlib
import subprocess
import sys

import pytest

from tools.firmware import prepare_diag_batch_sdk as sdk
from tools.firmware.tests.test_ownership_link_audit import crosscompiler


@pytest.fixture
def member(tmp_path, crosscompiler):
    source = tmp_path / 'member.S'
    source.write_text('''.syntax unified
.thumb
.section .text.buf_diag_handle_alloc_failure,"ax"
.type buf_diag_handle_alloc_failure,%function
.thumb_func
buf_diag_handle_alloc_failure:
movs r0,#19
b.w zdo_diagnostics_inc
.size buf_diag_handle_alloc_failure,.-buf_diag_handle_alloc_failure
.section .text.zb_buf_get_func,"ax"
.global zb_buf_get_func
.type zb_buf_get_func,%function
.thumb_func
zb_buf_get_func:
ldr r0,1f
movs r1,#0
b.w zb_schedule_callback
.balign 4
1: .word buf_diag_handle_alloc_failure
.size zb_buf_get_func,.-zb_buf_get_func

.section .text.zb_buf_get_hipri_func,"ax"
.global zb_buf_get_hipri_func
.type zb_buf_get_hipri_func,%function
.thumb_func
zb_buf_get_hipri_func:
bx lr
.size zb_buf_get_hipri_func,.-zb_buf_get_hipri_func

.section .text.zb_buf_get_out_delayed_func,"ax"
.global zb_buf_get_out_delayed_func
.type zb_buf_get_out_delayed_func,%function
.thumb_func
zb_buf_get_out_delayed_func:
bx lr
.size zb_buf_get_out_delayed_func,.-zb_buf_get_out_delayed_func

.section .text.zb_buf_get_in_delayed_func,"ax"
.global zb_buf_get_in_delayed_func
.type zb_buf_get_in_delayed_func,%function
.thumb_func
zb_buf_get_in_delayed_func:
bx lr
.size zb_buf_get_in_delayed_func,.-zb_buf_get_in_delayed_func

.section .text.zb_buf_get_out_delayed_ext_func,"ax"
.global zb_buf_get_out_delayed_ext_func
.type zb_buf_get_out_delayed_ext_func,%function
.thumb_func
zb_buf_get_out_delayed_ext_func:
bx lr
.size zb_buf_get_out_delayed_ext_func,.-zb_buf_get_out_delayed_ext_func

.section .text.zb_buf_get_in_delayed_ext_func,"ax"
.global zb_buf_get_in_delayed_ext_func
.type zb_buf_get_in_delayed_ext_func,%function
.thumb_func
zb_buf_get_in_delayed_ext_func:
bx lr
.size zb_buf_get_in_delayed_ext_func,.-zb_buf_get_in_delayed_ext_func

.section .text.process_delayed_buf_entry_unsafe,"ax"
.type process_delayed_buf_entry_unsafe,%function
.thumb_func
process_delayed_buf_entry_unsafe:
bx lr
.size process_delayed_buf_entry_unsafe,.-process_delayed_buf_entry_unsafe
''')
    target = tmp_path / 'zb_bufpool_mult.o'
    subprocess.run([str(crosscompiler), '-mcpu=cortex-m4', '-mthumb', '-c', str(source),
                    '-o', str(target)], check=True, capture_output=True, text=True)
    return target, crosscompiler.with_name('arm-zephyr-eabi-objcopy')


def test_symbol_export_preserves_allocated_bytes_and_relocations(tmp_path, member):
    source, objcopy = member
    raw = source.read_bytes()
    output = tmp_path / 'exported.o'
    report = sdk.transform_member(source, output, objcopy)
    assert report['allocated_sections_unchanged']
    assert report['normalized_relocations_unchanged']
    assert report['exported_symbol'] == 'vimar_sdk_buf_diag_handle_alloc_failure'
    assert report['derived_sha256'] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert source.read_bytes() == raw


def test_native_getter_has_separate_real_entry_for_internal_interposition(tmp_path, member):
    source, objcopy = member
    output = tmp_path / 'exported.o'
    sdk.transform_member(source, output, objcopy)
    elf = sdk.ELFFile(sdk.io.BytesIO(output.read_bytes()))
    symbols = elf.get_section_by_name('.symtab')
    getter = symbols.get_symbol_by_name('zb_buf_get_func')[0]
    real = symbols.get_symbol_by_name('vimar_sdk_buf_get_func') or []
    assert getter['st_info']['bind'] == 'STB_WEAK'
    assert len(real) == 1 and real[0]['st_info']['bind'] == 'STB_GLOBAL'
    assert real[0]['st_value'] == getter['st_value']
    assert real[0]['st_size'] == getter['st_size'] > 0
    assert real[0]['st_shndx'] == getter['st_shndx']


def test_changed_instruction_rejected(tmp_path, member):
    source, objcopy = member
    output = tmp_path / 'exported.o'
    sdk.transform_member(source, output, objcopy)
    raw = bytearray(output.read_bytes())
    offset = sdk.ELFFile(sdk.io.BytesIO(raw)).get_section_by_name('.text.buf_diag_handle_alloc_failure')['sh_offset']
    raw[offset] ^= 1
    with pytest.raises(ValueError, match='allocated'):
        sdk.verify_member(source.read_bytes(), bytes(raw))


def test_source_alias_rejected(member):
    source, objcopy = member
    raw = source.read_bytes()
    with pytest.raises(ValueError, match='source'):
        sdk.transform_member(source, source, objcopy)
    assert source.read_bytes() == raw


def test_unreviewed_archive_rejected_before_tools(tmp_path):
    source = tmp_path / 'unreviewed.a'
    source.write_bytes(b'not a reviewed archive')
    with pytest.raises(ValueError, match='archive'):
        sdk.prepare_archive(source, tmp_path / 'out/libzboss.a', Path('/absent/ar'), Path('/absent/objcopy'))
    assert not (tmp_path / 'out/libzboss.a').exists()


def test_report_cannot_overwrite_source(tmp_path, monkeypatch):
    source = tmp_path / 'input.a'
    source.write_bytes(b'preserved input')
    monkeypatch.setattr(sys, 'argv', ['prepare', '--archive', str(source),
                        '--output', str(tmp_path / 'out.a'), '--report', str(source),
                        '--ar', '/absent/ar', '--objcopy', '/absent/objcopy'])
    with pytest.raises(ValueError, match='source'):
        sdk.main()
    assert source.read_bytes() == b'preserved input'

@pytest.fixture
def diagnostics_member(tmp_path, crosscompiler):
    source=tmp_path/'diagnostics.S'
    source.write_text('''.syntax unified
.thumb
.section .text.zdo_diagnostics_inc,"ax"
.global zdo_diagnostics_inc
.type zdo_diagnostics_inc,%function
.thumb_func
zdo_diagnostics_inc:
.space 0x30
movs r0,#31
b.w zb_nvram_write_dataset
.size zdo_diagnostics_inc,.-zdo_diagnostics_inc
''')
    output=tmp_path/'zdo_diagnostics.o'
    subprocess.run([str(crosscompiler),'-mcpu=cortex-m4','-mthumb','-c',str(source),'-o',str(output)],check=True,capture_output=True)
    return output,crosscompiler.with_name('arm-zephyr-eabi-objcopy')


def test_statistics_binding_is_volatile_without_instruction_changes(tmp_path, diagnostics_member):
    source,objcopy=diagnostics_member;output=tmp_path/'volatile.o'
    result=sdk.transform_diagnostics_member(source,output,objcopy)
    assert result['allocated_sections_unchanged']
    assert result['normalized_relocations_unchanged']
    assert result['redirected_calls']==1
    elf=sdk.ELFFile(sdk.io.BytesIO(output.read_bytes()))
    assert elf.get_section_by_name('.symtab').get_symbol_by_name('vimar_diag_statistics_checkpoint')
    assert not elf.get_section_by_name('.symtab').get_symbol_by_name('zb_nvram_write_dataset')


def test_changed_diagnostic_dataset_or_instructions_are_rejected(tmp_path, diagnostics_member):
    source,objcopy=diagnostics_member;output=tmp_path/'volatile.o'
    sdk.transform_diagnostics_member(source,output,objcopy)
    raw=bytearray(output.read_bytes())
    offset=sdk.ELFFile(sdk.io.BytesIO(raw)).get_section_by_name('.text.zdo_diagnostics_inc')['sh_offset']
    raw[offset+0x30]^=1
    with pytest.raises(ValueError):sdk.verify_diagnostics_member(source.read_bytes(),bytes(raw))


def test_all_native_allocation_entry_aliases_are_separate_weak_seams(tmp_path, member):
    source,objcopy=member;output=tmp_path/'all-seams.o'
    sdk.transform_member(source,output,objcopy)
    symbols=sdk.ELFFile(sdk.io.BytesIO(output.read_bytes())).get_section_by_name('.symtab')
    for name in ('zb_buf_get_hipri_func','zb_buf_get_out_delayed_func','zb_buf_get_in_delayed_func',
                 'zb_buf_get_out_delayed_ext_func','zb_buf_get_in_delayed_ext_func',
                 'process_delayed_buf_entry_unsafe'):
        native=symbols.get_symbol_by_name(name)[0]
        real=symbols.get_symbol_by_name('vimar_sdk_'+name)
        assert native['st_info']['bind']=='STB_WEAK',name
        assert real and real[0]['st_info']['bind']=='STB_GLOBAL',name
        assert real[0]['st_size']==native['st_size']>0
        assert real[0]['st_value']==native['st_value']
        assert real[0]['st_shndx']==native['st_shndx']
