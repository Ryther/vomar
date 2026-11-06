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


def test_analysis_recorder_profile_is_frozen_separately_from_compact_main(tmp_path, monkeypatch):
    from tools.release.ci_firmware import build_trace_main
    _, pair, loader = fixture_source(tmp_path, monkeypatch)
    # Exercise real configuration/hash preparation without invoking the SDK.
    monkeypatch.setattr(builder, 'build', builder.prepare)
    compact = builder.prepare(tmp_path / 'compact', pair, loader)
    traced = build_trace_main(tmp_path / 'traced', pair, loader)
    assert 'CONFIG_VIMAR_LOOP_TRACE=y\n' in (tmp_path / 'traced/main.conf').read_text()
    assert traced['build_id'] != compact['build_id']
    assert traced['inputs_sha256']['main.conf'] != compact['inputs_sha256']['main.conf']
    after = builder.prepare(tmp_path / 'after', pair, loader)
    assert (tmp_path / 'after/main.conf').read_bytes() == (tmp_path / 'compact/main.conf').read_bytes()
    assert after['build_id'] == compact['build_id']


def test_failed_analysis_profile_does_not_change_subsequent_compact_main(tmp_path, monkeypatch):
    from tools.release.ci_firmware import build_trace_main
    _, pair, loader = fixture_source(tmp_path, monkeypatch)
    monkeypatch.setattr(builder, 'build', builder.prepare)
    before = builder.prepare(tmp_path / 'before', pair, loader)
    occupied = tmp_path / 'occupied'
    occupied.mkdir()
    with pytest.raises(ValueError):
        build_trace_main(occupied, pair, loader)
    after = builder.prepare(tmp_path / 'after', pair, loader)
    assert after['build_id'] == before['build_id']
    assert 'CONFIG_VIMAR_LOOP_TRACE=n\n' in (tmp_path / 'after/main.conf').read_text()


def test_ci_entrypoint_prepares_both_compact_and_recorder_profiles(tmp_path, monkeypatch):
    import sys
    from tools.release import ci_firmware
    source, _, _ = fixture_source(tmp_path, monkeypatch)
    monkeypatch.setattr(ci_firmware, 'ROOT', source)
    monkeypatch.setattr(builder, 'build', builder.prepare)
    for name, value in {'VIMAR_NCS_WORKSPACE': str(tmp_path),
                        'VIMAR_WEST': '/synthetic/west',
                        'VIMAR_BUILD_PYTHON': '/synthetic/python'}.items():
        monkeypatch.setenv(name, value)

    def native_boundary(command, **kwargs):
        if 'tools.firmware.build_typed_common_candidate' in command:
            generated = Path(command[command.index('--output') + 1]) / 'generated'
            generated.mkdir(parents=True)
            for name in ('main-pair.h', 'loader-contracts.h'):
                (generated / name).write_text('/* synthetic binding */\n')
        elif 'tools.firmware.build_guarded_main' in command:
            builder.prepare(*[command[command.index(flag) + 1] for flag in
                              ('--output', '--pair-bindings', '--loader-bindings')])
        elif '-c' in command:
            with monkeypatch.context() as child:
                child.setattr(sys, 'argv', command[1:2] + command[3:])
                exec(command[2], {})
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(ci_firmware.subprocess, 'run', native_boundary)
    out = tmp_path / 'ci-output'
    monkeypatch.setattr(sys, 'argv', ['ci_firmware', '--output', str(out)])
    ci_firmware.main()
    assert 'CONFIG_VIMAR_LOOP_TRACE=n\n' in (out / 'guarded-main/main.conf').read_text()
    assert 'CONFIG_VIMAR_LOOP_TRACE=y\n' in (out / 'loop-trace-main/main.conf').read_text()
