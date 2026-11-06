"""Prepare a verified symbol-only copy of the pinned precompiled SDK archive."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection

ARCHIVE_SHA = '879bc7c8f39a8c66a02ad119db50a4c637835c572f1277bba88aff51a826ebf0'
MEMBER = 'zb_bufpool_mult.o'
LOCAL = 'buf_diag_handle_alloc_failure'
EXPORTED = 'vimar_sdk_buf_diag_handle_alloc_failure'
DIAGNOSTICS_MEMBER = 'zdo_diagnostics.o'
RAM_CHECKPOINT = 'vimar_diag_statistics_checkpoint'
GETTER = 'zb_buf_get_func'
REAL_GETTER = 'vimar_sdk_buf_get_func'
ALLOCATION_ENTRIES = {GETTER: REAL_GETTER, **{
    name: 'vimar_sdk_' + name for name in (
        'zb_buf_get_hipri_func', 'zb_buf_get_out_delayed_func', 'zb_buf_get_in_delayed_func',
        'zb_buf_get_out_delayed_ext_func', 'zb_buf_get_in_delayed_ext_func',
        'process_delayed_buf_entry_unsafe')}}


def allocated(elf):
    return {section.name: (section['sh_flags'], section['sh_size'], section.data())
            for section in elf.iter_sections() if section['sh_flags'] & 2}


def relocations(elf, renamed=None):
    rows = []
    for section in elf.iter_sections():
        if not isinstance(section, RelocationSection):
            continue
        table = elf.get_section(section['sh_link'])
        target = elf.get_section(section['sh_info']).name
        for row in section.iter_relocations():
            symbol = table.get_symbol(row['r_info_sym'])
            name = (renamed or {LOCAL: EXPORTED}).get(symbol.name, symbol.name)
            rows.append((target, row['r_offset'], row['r_info_type'], name,
                         row['r_addend'] if row.is_RELA() else None))
    return sorted(rows)


def verify_member(original: bytes, derived: bytes) -> dict:
    before, after = ELFFile(io.BytesIO(original)), ELFFile(io.BytesIO(derived))
    if before['e_machine'] != 'EM_ARM' or after['e_machine'] != 'EM_ARM':
        raise ValueError('Reviewed ARM object required')
    old = before.get_section_by_name('.symtab').get_symbol_by_name(LOCAL) or []
    new = after.get_section_by_name('.symtab').get_symbol_by_name(EXPORTED) or []
    if len(old) != 1 or len(new) != 1:
        raise ValueError('Exactly one reviewed diagnostic callback required')
    old, new = old[0], new[0]
    if (old['st_info']['bind'] != 'STB_LOCAL' or new['st_info']['bind'] != 'STB_GLOBAL'
            or old['st_info']['type'] != 'STT_FUNC' or new['st_info']['type'] != 'STT_FUNC'
            or old['st_value'] != new['st_value'] or old['st_size'] != new['st_size']
            or old['st_size'] != 6):
        raise ValueError('Diagnostic callback binding or ABI changed')
    if after.get_section_by_name('.symtab').get_symbol_by_name(LOCAL):
        raise ValueError('Unconverted local callback remains')
    original_getter = before.get_section_by_name('.symtab').get_symbol_by_name(GETTER) or []
    weak_getter = after.get_section_by_name('.symtab').get_symbol_by_name(GETTER) or []
    real_getter = after.get_section_by_name('.symtab').get_symbol_by_name(REAL_GETTER) or []
    if len(original_getter) != 1 or len(weak_getter) != 1 or len(real_getter) != 1:
        raise ValueError('Exactly one native getter and real-entry alias required')
    original_getter, weak_getter, real_getter = original_getter[0], weak_getter[0], real_getter[0]
    if (original_getter['st_info']['bind'] != 'STB_GLOBAL'
            or weak_getter['st_info']['bind'] != 'STB_WEAK'
            or real_getter['st_info']['bind'] != 'STB_GLOBAL'
            or before.get_section_by_name('.symtab').get_symbol_by_name(REAL_GETTER)):
        raise ValueError('Native getter interposition bindings changed')
    for symbol in (weak_getter, real_getter):
        if (symbol['st_info']['type'] != 'STT_FUNC'
                or symbol['st_value'] != original_getter['st_value']
                or symbol['st_size'] != original_getter['st_size']
                or symbol['st_size'] == 0
                or after.get_section(symbol['st_shndx']).name != '.text.' + GETTER):
            raise ValueError('Native getter real-entry ABI changed')
    for name, alias in ALLOCATION_ENTRIES.items():
        old_rows = before.get_section_by_name('.symtab').get_symbol_by_name(name) or []
        weak_rows = after.get_section_by_name('.symtab').get_symbol_by_name(name) or []
        real_rows = after.get_section_by_name('.symtab').get_symbol_by_name(alias) or []
        if len(old_rows) != 1 or len(weak_rows) != 1 or len(real_rows) != 1:
            raise ValueError('Missing allocation entry seam: ' + name)
        old, weak, real = old_rows[0], weak_rows[0], real_rows[0]
        binding = 'STB_LOCAL' if name == 'process_delayed_buf_entry_unsafe' else 'STB_GLOBAL'
        if (old['st_info']['bind'] != binding or weak['st_info']['bind'] != 'STB_WEAK'
                or real['st_info']['bind'] != 'STB_GLOBAL'
                or before.get_section_by_name('.symtab').get_symbol_by_name(alias)):
            raise ValueError('Allocation entry binding changed: ' + name)
        for symbol in (weak, real):
            if (symbol['st_info']['type'] != 'STT_FUNC' or symbol['st_size'] != old['st_size']
                    or symbol['st_size'] == 0 or symbol['st_value'] != old['st_value']
                    or after.get_section(symbol['st_shndx']).name != '.text.' + name):
                raise ValueError('Allocation entry ABI changed: ' + name)
    if allocated(before) != allocated(after):
        raise ValueError('SDK allocated bytes changed')
    if relocations(before) != relocations(after):
        raise ValueError('SDK relocations changed')
    return dict(original_sha256=hashlib.sha256(original).hexdigest(),
                derived_sha256=hashlib.sha256(derived).hexdigest(),
                allocated_sections_unchanged=True, normalized_relocations_unchanged=True,
                allocated_sections=len(allocated(after)), relocations=len(relocations(after)),
                exported_symbol=EXPORTED, native_getter_interposed=True,
                real_getter=REAL_GETTER, getter_size=real_getter['st_size'],
                allocation_entries=ALLOCATION_ENTRIES)


def different_source(source: Path, output: Path):
    if (source.resolve() == output.resolve()
            or source.exists() and output.exists() and source.samefile(output)):
        raise ValueError('Output must not alias the source')


def transform_member(source: Path, output: Path, objcopy: Path) -> dict:
    different_source(source, output)
    original = source.read_bytes()
    elf = ELFFile(io.BytesIO(original))
    getters = elf.get_section_by_name('.symtab').get_symbol_by_name(GETTER) or []
    if len(getters) != 1 or elf.elfclass != 32 or not elf.little_endian:
        raise ValueError('Reviewed ELF32 little-endian native getter required')
    entries = {}
    for name in ALLOCATION_ENTRIES:
        rows = elf.get_section_by_name('.symtab').get_symbol_by_name(name) or []
        if len(rows) != 1:
            raise ValueError('Reviewed allocation entry required: ' + name)
        entries[name] = rows[0]
    subprocess.run([str(objcopy), '--globalize-symbol=' + EXPORTED,
                    '--redefine-sym=' + LOCAL + '=' + EXPORTED,
                    '--globalize-symbol=process_delayed_buf_entry_unsafe', str(source), str(output)],
                   check=True, capture_output=True, text=True)
    arguments = [str(objcopy)]
    for name, alias in ALLOCATION_ENTRIES.items():
        arguments += ['--weaken-symbol=' + name,
                      '--add-symbol=' + alias + '=.text.' + name + ':'
                      + str(entries[name]['st_value']) + ',global,function']
    subprocess.run([*arguments, str(output)], check=True, capture_output=True, text=True)
    # objcopy creates size-zero aliases; restore only ELF symbol-size metadata.
    derived = bytearray(output.read_bytes())
    table = ELFFile(io.BytesIO(derived)).get_section_by_name('.symtab')
    for name, alias in ALLOCATION_ENTRIES.items():
        aliases = [(index, symbol) for index, symbol in enumerate(table.iter_symbols())
                   if symbol.name == alias]
        if len(aliases) != 1 or aliases[0][1]['st_size'] != 0:
            raise ValueError('Unexpected allocation alias metadata: ' + name)
        struct.pack_into('<I', derived, table['sh_offset'] + aliases[0][0] * table['sh_entsize'] + 8,
                         entries[name]['st_size'])
    output.write_bytes(derived)
    report = verify_member(original, output.read_bytes())
    if source.read_bytes() != original:
        raise ValueError('Source member changed during conversion')
    return report


def verify_diagnostics_member(original: bytes, derived: bytes) -> dict:
    before, after = ELFFile(io.BytesIO(original)), ELFFile(io.BytesIO(derived))
    if before['e_machine'] != 'EM_ARM' or after['e_machine'] != 'EM_ARM':
        raise ValueError('Reviewed ARM diagnostics object required')
    calls = [r for r in relocations(before) if r[3] == 'zb_nvram_write_dataset']
    section = before.get_section_by_name('.text.zdo_diagnostics_inc')
    if (calls != [('.text.zdo_diagnostics_inc', 0x32, 30, 'zb_nvram_write_dataset', None)]
            or section is None or section.data()[0x30:0x32] != b'\x1f\x20'):
        raise ValueError('Unreviewed diagnostic persistence edge or dataset')
    if allocated(before) != allocated(after):
        raise ValueError('SDK allocated diagnostics bytes changed')
    if relocations(before, {'zb_nvram_write_dataset': RAM_CHECKPOINT}) != relocations(after):
        raise ValueError('Unexpected diagnostics relocation change')
    symbols = after.get_section_by_name('.symtab')
    target = symbols.get_symbol_by_name(RAM_CHECKPOINT) or []
    if (len(target) != 1 or target[0]['st_shndx'] != 'SHN_UNDEF'
            or symbols.get_symbol_by_name('zb_nvram_write_dataset')):
        raise ValueError('Diagnostic policy binding is not exclusively volatile')
    return dict(original_sha256=hashlib.sha256(original).hexdigest(),
                derived_sha256=hashlib.sha256(derived).hexdigest(),
                allocated_sections_unchanged=True, normalized_relocations_unchanged=True,
                redirected_calls=1, dataset=31, policy_symbol=RAM_CHECKPOINT)


def transform_diagnostics_member(source: Path, output: Path, objcopy: Path) -> dict:
    different_source(source, output)
    original = source.read_bytes()
    subprocess.run([str(objcopy), '--redefine-sym=zb_nvram_write_dataset=' + RAM_CHECKPOINT,
                    str(source), str(output)], check=True, capture_output=True, text=True)
    report = verify_diagnostics_member(original, output.read_bytes())
    if source.read_bytes() != original:
        raise ValueError('Source diagnostics object changed')
    return report


def prepare_archive(source: Path, output: Path, ar: Path, objcopy: Path) -> dict:
    different_source(source, output)
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ARCHIVE_SHA:
        raise ValueError('Unreviewed SDK archive')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='diag-sdk-', dir=output.parent) as temporary:
        staging = Path(temporary)
        original = staging / 'original.o'
        original.write_bytes(subprocess.run([str(ar), 'p', str(source), MEMBER],
                                            check=True, capture_output=True).stdout)
        member = staging / MEMBER
        report = transform_member(original, member, objcopy)
        diagnostics_original = staging / 'diagnostics-original.o'
        diagnostics_original.write_bytes(subprocess.run([str(ar), 'p', str(source), DIAGNOSTICS_MEMBER],
                                                         check=True, capture_output=True).stdout)
        diagnostics = staging / DIAGNOSTICS_MEMBER
        report['volatile_statistics'] = transform_diagnostics_member(diagnostics_original, diagnostics, objcopy)
        archive = staging / 'libzboss.a'
        archive.write_bytes(raw)
        subprocess.run([str(ar), 'rDs', str(archive), str(member), str(diagnostics)],
                       check=True, capture_output=True, text=True)
        packed = subprocess.run([str(ar), 'p', str(archive), MEMBER],
                                check=True, capture_output=True).stdout
        packed_diagnostics = subprocess.run([str(ar), 'p', str(archive), DIAGNOSTICS_MEMBER],
                                            check=True, capture_output=True).stdout
        if packed != member.read_bytes() or packed_diagnostics != diagnostics.read_bytes():
            raise ValueError('Derived archive does not contain the verified member')
        if source.read_bytes() != raw:
            raise ValueError('Original SDK archive changed')
        report.update(source=str(source.resolve()), source_sha256=ARCHIVE_SHA,
                      archive=str(output.resolve()),
                      archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
        shutil.move(str(archive), output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ar', type=Path, required=True)
    parser.add_argument('--objcopy', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    different_source(args.archive, args.report)
    different_source(args.output, args.report)
    result = prepare_archive(args.archive, args.output, args.ar, args.objcopy)
    args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
