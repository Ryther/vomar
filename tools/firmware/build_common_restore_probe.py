#!/usr/bin/env python3
"""Isolated unsigned common RESTORE/bootstrap SDK fit and SRAM-code proof.

No hardware or signing. The finite public loader-family digest is explicit.
Without --restore-image the bootstrap embeds the just-built UNSIGNED body:
its real signature/role validator rejects it, so that ELF is fit evidence only.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/firmware'))
from toolchain_paths import toolchain_paths
from build_loader_contract_bindings import generate
from loader_runtime_contract import COMMON_KIND
from validate_recovery import read_config,validate_uicr_preservation

def sha(data):return hashlib.sha256(data).hexdigest()

def binding_header(family):
    if not isinstance(family,str) or not re.fullmatch('[0-9a-f]{64}',family):raise ValueError('explicit lowercase common code-family SHA256 required')
    return generate([dict(kind=COMMON_KIND,sha256=family)]).decode('ascii')

def validate_output(output):
    output=Path(output).resolve()
    if output.is_relative_to(ROOT/'inputs') or (output.exists() and any(output.iterdir())):
        raise ValueError('output must be new/empty and outside immutable inputs')
    return output

def ram_call_graph(disassembly,roots):
    functions={};current=None
    for line in disassembly.splitlines():
        match=re.match(r'^([0-9a-fA-F]+) <([^>]+)>:',line)
        if match:current=match[2];functions[current]=[int(match[1],16),[]]
        elif current:functions[current][1].append(line)
    pending=list(roots);seen=set()
    while pending:
        name=pending.pop()
        if name in seen:continue
        if name not in functions:raise ValueError('missing critical RAM symbol: '+name)
        address,lines=functions[name]
        if not 0x20000000<=address<0x20040000:raise ValueError('critical function is not in SRAM: '+name)
        seen.add(name)
        for line in lines:
            target=re.search(r'\b(?:blx?|b(?:\.[nw])?)\s+([0-9a-fA-F]+)\s+<([^>]+)>',line)
            if target:
                if not 0x20000000<=int(target[1],16)<0x20040000:raise ValueError('RAM function branches into FLASH: '+line.strip())
                callee=target[2].split('+')[0]
                if callee in functions and callee not in seen:pending.append(callee)
    return sorted(seen)

def inspect_elf(path,base,limit,objdump,output):
    from elftools.elf.elffile import ELFFile
    with path.open('rb') as file:
        elf=ELFFile(file)
        loads=[dict(vaddr=int(s['p_vaddr']),paddr=int(s['p_paddr']),filesz=int(s['p_filesz']),memsz=int(s['p_memsz'])) for s in elf.iter_segments() if s['p_type']=='PT_LOAD']
        symbols={s.name:dict(address=int(s['st_value'])&~1,size=int(s['st_size'])) for s in elf.get_section_by_name('.symtab').iter_symbols() if s.name}
        rom=[s for s in loads if s['filesz'] and s['paddr']<0x100000]
        if not rom or any(s['paddr']<base or s['paddr']+s['filesz']>base+limit for s in rom):raise ValueError('ROM load image exceeds its fixed stock-restoration boundary')
        used=max(s['paddr']+s['filesz'] for s in rom)-base
        ram=[s for s in loads if 0x20000000<=s['vaddr']<0x20040000]
        if any(s['vaddr']+s['memsz']>0x20040000 for s in ram):raise ValueError('RAM image exceeds nRF52840 SRAM')
        ram_end=max((s['vaddr']+s['memsz'] for s in ram),default=0x20000000)
    disassembly=subprocess.run([str(objdump),'-d',str(path)],check=True,capture_output=True,text=True).stdout
    output.write_text(disassembly)
    required=['ram_entry','ram_guard','ram_erase','ram_write','ram_read','wait_ready','rtc_now','force_off',
              'common_restore_finalizer_core','common_restore_monitor_sample','common_restore_monitor_guard',
              'candidate_power_protection_sample','candidate_power_protection_blocked']
    roots=set()
    for name in required:
        matches=[key for key in symbols if key==name or key.startswith(name+'.')]
        if not matches:raise ValueError('missing required SRAM function: '+name)
        for key in matches:
            value=symbols[key]
            if not 0x20000000<=value['address']<0x20040000 or value['address']+value['size']>0x20040000:
                raise ValueError('critical code is not completely in SRAM: '+key)
            roots.add(key)
    graph=ram_call_graph(disassembly,roots)
    return dict(rom_bytes=used,rom_limit=limit,rom_margin=limit-used,ram_extent=ram_end-0x20000000,
                loads=loads,ram_functions={k:symbols[k] for k in graph},ram_call_graph=graph,
                disassembly_sha256=sha(disassembly.encode()))

def build_probe(output,family,restore_image=None):
    output=validate_output(output);header=binding_header(family);paths=toolchain_paths()
    public=paths['public_key'].read_bytes()
    if not public.startswith(b'-----BEGIN PUBLIC KEY-----') or b'PRIVATE KEY' in public:raise ValueError('public-only verification key required')
    output.mkdir(parents=True,exist_ok=True)
    source=output/'source/firmware'
    shutil.copytree(ROOT/'firmware',source,ignore=shutil.ignore_patterns('keys','__pycache__'))
    bindings=output/'loader-contracts.h';bindings.write_text(header)
    report=dict(schema_version=1,kind='unsigned-common-stock-restoration-source-fit',hardware_qualified=False,
                deployable=False,signed=False,private_key_read=False,family_contract=dict(kind=COMMON_KIND,sha256=family),
                binding_sha256=sha(bindings.read_bytes()),public_key_sha256=sha(public),builder_sha256=sha(Path(__file__).read_bytes()),
                source_sha256={str(p.relative_to(output/'source')):sha(p.read_bytes()) for p in source.rglob('*') if p.is_file()},commands=[],builds={})
    manifest=output/'probe-manifest.json'
    def save():manifest.write_text(json.dumps(report,indent=2)+'\n')
    save()
    for mode in ['restorer','bootstrap']:
        config=output/(mode+'.conf')
        config.write_text('CONFIG_VIMAR_COMMON_RESTORE_EXPERIMENTAL=y\nCONFIG_DISABLE_FLASH_PATCH=n\nCONFIG_MCUBOOT_SIGNATURE_KEY_FILE=""\n'+
                          ('CONFIG_VIMAR_COMMON_RESTORE_BOOTSTRAP=y\n' if mode=='bootstrap' else ''))
        build=output/(mode+'-build')
        configs=[source/'common_restore/prj.conf',source/'research/vimar-candidate.conf',config]
        args=['-DCONF_FILE='+';'.join(map(str,configs)),
              '-DDTC_OVERLAY_FILE='+';'.join(map(str,[source/'common_restore'/(mode+'.overlay'),source/'research/vimar-candidate.overlay'])),
              '-DVIMAR_LOADER_CONTRACT_BINDINGS_HEADER='+str(bindings)]
        if mode=='bootstrap':
            configs.insert(1,source/'ota/crypto.conf');args[0]='-DCONF_FILE='+';'.join(map(str,configs))
            blob=Path(restore_image).resolve().read_bytes() if restore_image else (output/'restorer-build/zephyr/zephyr.bin').read_bytes()
            if not blob or len(blob)>0x3f000:raise ValueError('embedded RESTORE input exceeds its exact scratch bound')
            blob_header=output/'restorer-blob.h'
            blob_header.write_text('/* Explicit embedded bytes; unsigned fit input is not execution authority. */\n#include <stdint.h>\nstatic const uint8_t common_restore_blob[] = {\n'+
                                   ','.join('0x%02x'%b for b in blob)+'\n};\n')
            report['embedded_restore']=dict(sha256=sha(blob),size=len(blob),input=str(Path(restore_image).resolve()) if restore_image else 'derived UNSIGNED restorer body; real validation MUST reject',
                                           execution_authentication_claimed=False)
            args+=['-DVIMAR_COMMON_RESTORE_BLOB_HEADER='+str(blob_header)]
        command=[str(paths['west']),'build','--pristine','--no-sysbuild','-b','nrf52840dk/nrf52840',str(source/'common_restore'),'-d',str(build),'--target','zephyr/zephyr.elf','--',*args]
        report['commands'].append(command);save()
        with (output/(mode+'-build.log')).open('w') as log:subprocess.run(command,cwd=paths['sdk'],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=900)
        values=read_config(build/'zephyr/.config')
        required=['CONFIG_VIMAR_COMMON_RESTORE_EXPERIMENTAL','CONFIG_CODE_DATA_RELOCATION','CONFIG_BT_SMP','CONFIG_BT_FIXED_PASSKEY','CONFIG_PSA_WANT_ALG_SHA_256','CONFIG_MPU_ALLOW_FLASH_WRITE']
        forbidden=['CONFIG_SETTINGS','CONFIG_NVS','CONFIG_BT_SETTINGS','CONFIG_WATCHDOG','CONFIG_MCUMGR','CONFIG_DISABLE_FLASH_PATCH','CONFIG_SOC_DCDC_NRF52X','CONFIG_SOC_DCDC_NRF52X_HV']
        if any(values.get(k)!='y' for k in required) or any(values.get(k)=='y' for k in forbidden):raise ValueError('effective adapter configuration violates isolated restoration contract')
        if values.get('CONFIG_MCUBOOT_SIGNATURE_KEY_FILE')!='""':raise ValueError('unsigned probe unexpectedly selects a signing key')
        defines=set(re.findall(r'-D([A-Za-z0-9_]+)',(build/'build.ninja').read_text()))
        validate_uicr_preservation({mode:values},{mode:defines})
        cache=(build/'CMakeCache.txt').read_text();match=re.search(r'^CMAKE_OBJDUMP:FILEPATH=(.+)$',cache,re.M)
        if not match:raise ValueError('native objdump tool path missing')
        proof=inspect_elf(build/'zephyr/zephyr.elf',0xb0000 if mode=='restorer' else 0xc000,0x3f000 if mode=='restorer' else 0xa2000,Path(match[1]),output/(mode+'-disassembly.txt'))
        if any((build/'zephyr').glob('*.signed.*')):raise ValueError('unexpected signed output')
        proof['artifacts']={p.name:dict(size=p.stat().st_size,sha256=sha(p.read_bytes())) for p in [build/'zephyr/zephyr.elf',build/'zephyr/zephyr.bin',build/'zephyr/.config',build/'zephyr/zephyr.map',build/'zephyr/zephyr.dts']}
        report['builds'][mode]=proof;save()
    report['status']='two unsigned ELF fits and reachable SRAM code checked; not a signed or physically qualified restoration set';save()
    return manifest

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path);parser.add_argument('--loader-family-sha256',required=True);parser.add_argument('--restore-image',type=Path)
    args=parser.parse_args();print(build_probe(args.output,args.loader_family_sha256,args.restore_image))
if __name__=='__main__':main()
