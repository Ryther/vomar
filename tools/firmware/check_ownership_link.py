"""Read-only audit of ownership hooks in a complete, relocation-bearing ARM ELF."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path

from elftools.elf.elffile import ELFFile

HOOKS = (
    'zb_bufpool_storage_init', 'zb_bufpool_storage_allocate',
    'zb_bufpool_storage_free', 'zb_buf_copy_func',
    'zb_buf_initial_alloc_func', 'zb_buf_reuse_func',
    'zb_nlde_data_request', 'zb_schedule_callback',
    'zb_nwk_handle_mcps_data_confirm',
)


def inspect(path: Path) -> dict:
    raw = path.read_bytes()
    with io.BytesIO(raw) as stream:
        elf = ELFFile(stream)
        if elf['e_machine'] != 'EM_ARM':
            raise ValueError('An ARM ELF is required')
        symbols = elf.get_section_by_name('.symtab')
        if symbols is None:
            raise ValueError('A complete symbol table is required')
        definitions = {s.name: s for s in symbols.iter_symbols()
                       if s['st_shndx'] != 'SHN_UNDEF'}
        functions = [(s['st_value'] & ~1, (s['st_value'] & ~1) + s['st_size'], s.name)
                     for s in definitions.values()
                     if s['st_info']['type'] == 'STT_FUNC' and s['st_size']]
        references = []
        for section in elf.iter_sections():
            if section['sh_type'] not in ('SHT_REL', 'SHT_RELA'):
                continue
            target = elf.get_section(section['sh_info'])
            if not target['sh_flags'] & 2:  # Allocated code/data, excluding debug records.
                continue
            table = elf.get_section(section['sh_link'])
            for relocation in section.iter_relocations():
                name = table.get_symbol(relocation['r_info_sym']).name
                if name not in HOOKS and name not in {'__wrap_' + h for h in HOOKS}:
                    continue
                address = relocation['r_offset']
                origin = next((n for lo, hi, n in functions if lo <= address < hi),
                              '<' + target.name + '>')
                references.append({'from': origin, 'to': name,
                                   'address': hex(address),
                                   'type': relocation['r_info_type']})
        missing = ['__wrap_' + h for h in HOOKS if '__wrap_' + h not in definitions]
        def edge(origin: str, destination: str) -> bool:
            return any(r['from'].startswith(origin) and r['to'] == destination
                       for r in references)
        checks = {
            'all_wrappers_defined': not missing,
            'central_allocation_intercepted': edge('allocate_buffer_unsafe',
                                                   '__wrap_zb_bufpool_storage_allocate'),
            'central_release_intercepted': edge('zb_buf_free_func',
                                                '__wrap_zb_bufpool_storage_free'),
            'storage_reset_intercepted': edge('zb_init_buffers',
                                              '__wrap_zb_bufpool_storage_init'),
            'real_nlde_uses_scheduler_hook': edge('zb_nlde_data_request',
                                                  '__wrap_zb_schedule_callback'),
            'aps_producer_intercepted': any('aps' in r['from'].lower() and
                                            r['to'] == '__wrap_zb_nlde_data_request'
                                            for r in references),
            'confirmation_proxy_intercepted': edge('zb_multimac_mcps_data_confirm_proxy',
                                                     '__wrap_zb_nwk_handle_mcps_data_confirm'),
        }
        lifecycle = set(HOOKS[:7])
        bypasses = [r for r in references if r['to'] in lifecycle and
                    r['from'] != '__wrap_' + r['to']]
        checks['no_lifecycle_or_producer_bypass'] = not bypasses
        if not references:
            raise ValueError('Allocated relocation records required; build with --emit-relocs')
    return {
        'elf': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(),
        'checks': checks, 'passed': all(checks.values()), 'missingWrappers': missing,
        'lifecycleOrProducerBypasses': bypasses, 'references': references,
        'hardwareQualified': False,
        'scope': 'Selected native link seams; not runtime or physical qualification.',
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('elf', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = inspect(args.elf)
    with args.output.open('w') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'passed': report['passed'], 'checks': report['checks']}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
