"""The preserved MAIN recipe must keep keys out and bind its exact inputs."""
from pathlib import Path
import json
import subprocess

import pytest

from tools.firmware import build_guarded_main as builder


def fixture_source(tmp_path, monkeypatch):
    source = tmp_path / 'repo'
    (source / 'firmware/keys').mkdir(parents=True)
    (source / 'firmware/VERSION').write_text(
        'VERSION_MAJOR = 1\nVERSION_MINOR = 1\nPATCHLEVEL = 7\nVERSION_TWEAK = 0\nEXTRAVERSION =\n')
    (source / 'firmware/main.c').write_text('/* synthetic source */\n')
    (source / 'firmware/keys/private.pem').write_text('synthetic excluded secret')
    (source / 'firmware/Kconfig.orig').write_text('synthetic excluded backup')
    (source / 'tools/firmware').mkdir(parents=True)
    for name in builder.HELPERS:
        (source / 'tools/firmware' / name).write_text('# synthetic helper\n')
    pair = tmp_path / 'pair.h'
    pair.write_text('/* reviewed synthetic pair */\n')
    loader = tmp_path / 'loader.h'
    loader.write_text('/* reviewed synthetic loader */\n')
    monkeypatch.setattr(builder, 'ROOT', source)
    return source, pair, loader


def test_preparation_excludes_keys_and_never_overwrites_output(tmp_path, monkeypatch):
    source, pair, loader = fixture_source(tmp_path, monkeypatch)
    out = tmp_path / 'prepared'
    report = builder.prepare(out, pair, loader)
    assert not (out / 'source/firmware/keys').exists()
    assert not (out / 'source/firmware/Kconfig.orig').exists()
    assert (out / 'generated/main-pair.h').read_bytes() == pair.read_bytes()
    assert (out / 'generated/loader-contracts.h').read_bytes() == loader.read_bytes()
    (source / 'firmware/main.c').write_text('changed after snapshot')
    assert (out / 'source/firmware/main.c').read_text() == '/* synthetic source */\n'
    assert report['hardware_access'] is False and report['signed'] is False
    with pytest.raises(ValueError, match='new|NEW'):
        builder.prepare(out, pair, loader)


def test_build_identity_changes_with_source_and_bindings(tmp_path, monkeypatch):
    source, pair, loader = fixture_source(tmp_path, monkeypatch)
    first = builder.prepare(tmp_path / 'first', pair, loader)['build_id']
    (source / 'firmware/main.c').write_text('changed source')
    second = builder.prepare(tmp_path / 'second', pair, loader)['build_id']
    assert second != first
    loader.write_text('changed loader bindings')
    assert builder.prepare(tmp_path / 'third', pair, loader)['build_id'] != second


def test_missing_binding_fails_before_creating_output(tmp_path, monkeypatch):
    _, pair, loader = fixture_source(tmp_path, monkeypatch)
    loader.unlink()
    out = tmp_path / 'absent'
    with pytest.raises((ValueError, FileNotFoundError)):
        builder.prepare(out, pair, loader)
    assert not out.exists()


def test_failed_native_build_retains_status_and_frozen_inputs(tmp_path, monkeypatch):
    _, pair, loader = fixture_source(tmp_path, monkeypatch)
    monkeypatch.setattr(builder, 'toolchain_paths', lambda: {
        'west': Path('/synthetic/west'), 'sdk': tmp_path})
    monkeypatch.setattr(builder.subprocess, 'run', lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 7))
    out = tmp_path / 'failed-build'
    with pytest.raises(subprocess.CalledProcessError):
        builder.build(out, pair, loader)
    report = json.loads((out / 'build-report.json').read_text())
    assert report['status'] == 'failed' and report['returncode'] == 7
    assert (out / 'source/firmware/main.c').exists()
    assert (out / 'generated/main-pair.h').read_bytes() == pair.read_bytes()
