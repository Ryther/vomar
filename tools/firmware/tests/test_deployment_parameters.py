"""Live helpers require an owner's endpoint/identity before contacting a device."""
import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools/firmware' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('script,args,missing', [
    ('tools/firmware/fade_walkthrough.py', [], '--ieee'),
    ('tools/firmware/fade_walkthrough.py', ['--ieee', '0x0011223344556677'], '--url'),
    ('tools/firmware/button_walkthrough.py', [], '--address'),
    ('tools/firmware/qualify_zigbee_ota.py', ['--ieee', '0x0011223344556677', '--image', 'absent', '--output', 'absent'], '--url'),
])
def test_missing_deployment_parameter_fails_before_access(script, args, missing):
    result = subprocess.run([sys.executable, str(ROOT / script), *args], capture_output=True, text=True)
    assert result.returncode == 2
    assert missing in result.stderr
    assert 'Traceback' not in result.stderr


@pytest.mark.parametrize('script,flag', [
    ('tools/firmware/fade_walkthrough.py', '--dry-run'),
    ('tools/firmware/button_walkthrough.py', '--plan'),
])
def test_offline_preview_needs_no_device_configuration(script, flag):
    result = subprocess.run([sys.executable, str(ROOT / script), flag], capture_output=True, text=True)
    assert result.returncode == 0


def test_fade_probe_get_request_uses_explicit_target():
    module = load('fade_walkthrough')
    frames = []
    probe = module.Probe('', 5, SimpleNamespace(emit=lambda *a, **kw: None), ieee='0x0011223344556677',
                         url='ws://localhost:8080/api', origin=None)
    async def send(raw):
        frames.append(json.loads(raw))
        from datetime import datetime, timezone
        probe.sequence += 1
        probe.state = {'brightness': 12, 'last_seen': datetime.now(timezone.utc).isoformat()}
    async def wait(predicate, timeout):
        assert predicate()
    probe.ws = SimpleNamespace(send=send)
    probe.wait = wait
    asyncio.run(probe.read(['brightness']))
    assert frames == [{'topic': '0x0011223344556677/get', 'payload': {'brightness': ''}}]


def test_button_hash_validation_binds_selected_release():
    module = load('button_walkthrough')
    images = [{'slot': 1, 'active': True, 'hash': 'a' * 64},
              {'slot': 0, 'active': False, 'hash': 'b' * 64}]
    module.validate_images(images, main_hash='b' * 64, recovery_hash='a' * 64)
    with pytest.raises(ValueError):
        module.validate_images(images, main_hash='c' * 64, recovery_hash='a' * 64)


def test_swd_missing_parameters_fail_without_launching_openocd(monkeypatch):
    spec = importlib.util.spec_from_file_location('watch_swd', ROOT / 'tools/hardware/watch_vimar_swd.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def forbidden(*args, **kwargs):
        pytest.fail('No hardware command may run before deployment parameters are supplied')
    monkeypatch.setattr(module.subprocess, 'run', forbidden)
    monkeypatch.setattr(sys, 'argv', ['watch_vimar_swd.py'])
    with pytest.raises(SystemExit) as failure:
        module.main()
    assert failure.value.code == 2


@pytest.mark.parametrize('name,args', [
    ('measure_boot', []), ('manual_power_cut', []), ('research_console', ['status']),
])
def test_other_live_tools_require_target_before_async_access(name, args, monkeypatch, capsys):
    module = load(name)
    def forbidden(coroutine):
        coroutine.close()
        pytest.fail('Missing target must fail before any asynchronous hardware access')
    monkeypatch.setattr(module.asyncio, 'run', forbidden)
    monkeypatch.setattr(sys, 'argv', [name, *args])
    with pytest.raises(SystemExit) as failure:
        module.main()
    assert failure.value.code == 2
    assert '--address' in capsys.readouterr().err


def test_provisioner_without_local_dk_denylist_refuses_hardware(monkeypatch, capsys):
    module = load('provision_vimar')
    monkeypatch.delenv('VIMAR_DK_DEVICE_IDS', raising=False)
    monkeypatch.setattr(sys, 'argv', ['provision_vimar', '--serial', '123', '--backup-only'])
    monkeypatch.setattr(module, 'detect', lambda *a: pytest.fail('No configured DK exclusion: no hardware access'))
    with pytest.raises(SystemExit) as failure:
        module.main()
    assert failure.value.code == 2
    assert '--dk-id' in capsys.readouterr().err


def test_stable_target_fails_closed_without_any_dk_exclusion(monkeypatch):
    module = load('provision_vimar')
    monkeypatch.setattr(module, 'KNOWN_DKS', set())
    assert module.stable_target([(1, 2)] * 3) is False
