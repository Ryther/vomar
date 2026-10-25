"""Capability requires the independently linked ARM loader, never a flag alone."""
import hashlib
import json
from pathlib import Path
import subprocess

import pytest


@pytest.fixture
def loader_probe(tmp_path):
    unsigned = tmp_path / 'unsigned'
    unsigned.mkdir()
    assembly = tmp_path / 'hook.s'
    assembly.write_text('.syntax unified\n.thumb\n.section .text\n.global vimar_inherited_watchdog_boot_gate\n.type vimar_inherited_watchdog_boot_gate,%function\n.thumb_func\nvimar_inherited_watchdog_boot_gate:\n bx lr\n.size vimar_inherited_watchdog_boot_gate, .-vimar_inherited_watchdog_boot_gate\n')
    subprocess.run(['arm-none-eabi-as', '-mcpu=cortex-m4', '-mthumb', '-o', str(tmp_path/'hook.o'), str(assembly)], check=True)
    subprocess.run(['arm-none-eabi-ld', '-Ttext=0x100', '-e', 'vimar_inherited_watchdog_boot_gate', '-o', str(unsigned/'zephyr.elf'), str(tmp_path/'hook.o')], check=True)
    (unsigned/'.config').write_text('CONFIG_VIMAR_INHERITED_WATCHDOG_HANDOFF=y\n')
    def refresh():
        manifest = dict(artifacts={name: dict(sha256=hashlib.sha256((unsigned/name).read_bytes()).hexdigest()) for name in ('.config','zephyr.elf')})
        (tmp_path/'probe-manifest.json').write_text(json.dumps(manifest))
    refresh()
    return tmp_path/'probe-manifest.json', refresh


def test_watchdog_capability_requires_actual_enabled_loader_symbol(loader_probe):
    from tools.firmware.build_typed_common_candidate import require_watchdog_loader
    manifest, _ = loader_probe
    proof = require_watchdog_loader(manifest)
    assert proof['symbol'] == 'vimar_inherited_watchdog_boot_gate'
    assert proof['address'] == 0x100
    assert proof['config_enabled'] is True
    assert proof['policy'] == 'paused-reset-before-main-v1'


@pytest.mark.parametrize('damage', ['disabled','renamed-symbol','stale-config','stale-elf'])
def test_descriptor_capability_cannot_follow_disabled_missing_or_unbound_loader(loader_probe,damage):
    from tools.firmware.build_typed_common_candidate import require_watchdog_loader
    manifest, refresh = loader_probe
    unsigned = manifest.parent/'unsigned'
    if damage in ('disabled','stale-config'):
        (unsigned/'.config').write_text('CONFIG_VIMAR_INHERITED_WATCHDOG_HANDOFF=n\n')
    else:
        subprocess.run(['arm-none-eabi-objcopy','--redefine-sym','vimar_inherited_watchdog_boot_gate=other_function',str(unsigned/'zephyr.elf')],check=True)
    if damage in ('disabled','renamed-symbol'):
        refresh()
    with pytest.raises(ValueError):
        require_watchdog_loader(manifest)


def test_unknown_builder_policy_fails_before_output_creation(tmp_path):
    from tools.firmware.build_typed_common_candidate import build
    output = tmp_path/'not-created'
    with pytest.raises(ValueError,match='watchdog'):
        build(output,tmp_path/'unused-public-registry',tmp_path/'unused-source-policy',watchdog_handoff='unknown')
    assert not output.exists()
