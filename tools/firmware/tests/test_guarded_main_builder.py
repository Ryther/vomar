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
    assert 'CONFIG_VIMAR_ALLOC_TRACE=y\n' in (tmp_path / 'traced/main.conf').read_text()
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


def test_production_builder_disables_allocation_capture():
    from tools.firmware.build_guarded_main import CONFIG
    assert 'CONFIG_VIMAR_ALLOC_TRACE=n' in CONFIG.splitlines()


def test_production_forwarders_preserve_native_results_without_capture(tmp_path):
    from tools.firmware.tests.test_zigbee_ownership_sdk import SDK
    root=Path(__file__).resolve().parents[3]
    (tmp_path/'zboss_api.h').write_text(SDK+'\ntypedef uint8_t zb_bool_t;typedef uint16_t zb_uint16_t;typedef void (*zb_callback2_t)(zb_uint8_t,zb_uint16_t);\n')
    harness=tmp_path/'forward.c'
    harness.write_text(r'''#include <assert.h>
#include <string.h>
#include "zigbee_alloc_passthrough.c"
static void cb(zb_uint8_t p){(void)p;}
static void cb2(zb_uint8_t p,zb_uint16_t q){(void)p;(void)q;}
zb_bufid_t vimar_sdk_buf_get_func(zb_bool_t in,zb_uint_t size){assert(in==1&&size==1216);return 19;}
zb_bufid_t vimar_sdk_zb_buf_get_hipri_func(zb_bool_t in){assert(!in);return 23;}
zb_ret_t vimar_sdk_zb_buf_get_out_delayed_func(zb_callback_t c){assert(c==cb);return -29;}
zb_ret_t vimar_sdk_zb_buf_get_in_delayed_func(zb_callback_t c){assert(c==cb);return -42;}
zb_ret_t vimar_sdk_zb_buf_get_out_delayed_ext_func(zb_callback2_t c,zb_uint16_t arg,zb_uint_t size){assert(c==cb2&&arg==0x1234&&size==2048);return -7;}
zb_ret_t vimar_sdk_zb_buf_get_in_delayed_ext_func(zb_callback2_t c,zb_uint16_t arg,zb_uint_t size){assert(c==cb2&&arg==0x1234&&size==2048);return -8;}
zb_bool_t vimar_sdk_process_delayed_buf_entry_unsafe(void *entry,zb_bool_t in){assert(entry==(void *)cb&&in==1);return 1;}
int main(void){assert(vimar_alloc_trace_enabled==0);assert(zb_buf_get_func(1,1216)==19);assert(zb_buf_get_hipri_func(0)==23);assert(zb_buf_get_out_delayed_func(cb)==-29);assert(zb_buf_get_in_delayed_func(cb)==-42);assert(zb_buf_get_out_delayed_ext_func(cb2,0x1234,2048)==-7);assert(zb_buf_get_in_delayed_ext_func(cb2,0x1234,2048)==-8);assert(process_delayed_buf_entry_unsafe((void *)cb,1)==1);uint8_t expected[21]={20,2};vimar_alloc_trace_boot(4);vimar_alloc_trace_storage_result(8,1);vimar_alloc_trace_failure();vimar_alloc_trace_release(1);vimar_alloc_trace_pool_reset();vimar_alloc_trace_refresh();vimar_alloc_trace_flush();assert(!memcmp(expected,vimar_alloc_trace_metadata,21));return 0;}
''')
    binary=tmp_path/'forward'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=undefined','-I',str(tmp_path),'-I',str(root/'firmware/src'),str(harness),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
