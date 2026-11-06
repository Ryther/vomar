"""Run the actual RAM recorder with synthetic SDK/OS boundaries, no vendor code."""
from pathlib import Path
import subprocess

import pytest
from tools.firmware.tests.test_zigbee_ownership_sdk import SDK

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope='module')
def executable(tmp_path_factory):
    directory = tmp_path_factory.mktemp('allocation-trace')
    (directory / 'zboss_api.h').write_text(SDK + '\ntypedef uint8_t zb_bool_t;\ntypedef uint16_t zb_uint16_t;\ntypedef void (*zb_callback2_t)(zb_uint8_t,zb_uint16_t);\n')
    (directory / 'zephyr').mkdir()
    (directory / 'zephyr/irq.h').write_text('unsigned irq_lock(void);\nvoid irq_unlock(unsigned);\n')
    (directory / 'zephyr/kernel.h').write_text('''#include <stdint.h>
#include <stdbool.h>
void *k_current_get(void);
bool k_is_in_isr(void);
uint32_t k_uptime_get_32(void);
''')
    (directory / 'trace-build-id.h').write_text('''#include <stdint.h>
extern volatile uint32_t synthetic_retained[64];
#define ALLOC_RETAINED synthetic_retained
static const uint8_t vimar_fault_build_id[16] = {0x55};
''')
    target = directory / 'recorder'
    command = ['cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
               '-fsanitize=undefined', '-fno-sanitize-recover=all',
               '-DVIMAR_FAULT_BUILD_ID_HEADER="trace-build-id.h"',
               '-I', str(directory), '-I', str(ROOT / 'firmware/src'),
               str(ROOT / 'tools/firmware/tests/zigbee_alloc_trace_test.c'),
               str(ROOT / 'firmware/src/zigbee_alloc_trace.c'), '-o', str(target)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return target


@pytest.mark.parametrize('case', ['quota', 'storage', 'history', 'holders', 'nested', 'missing', 'contexts', 'clock_wrap', 'isr', 'isr_holder', 'nested_capture', 'nested_flush'])
def test_compiled_allocation_capture(executable, case):
    result = subprocess.run([str(executable), case], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


def test_retained_commit_survives_new_process_and_rejects_damage(executable, tmp_path):
    import binascii
    import struct
    saved = tmp_path / 'retained.bin'
    result = subprocess.run([str(executable), 'retained_write', str(saved)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    original = saved.read_bytes()
    for offset in (0, 128):
        assert struct.unpack_from('<I', original, offset + 80)[0] == binascii.crc32(original[offset:offset + 80])
    def read(data, case):
        saved.write_bytes(data)
        result = subprocess.run([str(executable), case, str(saved)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    read(original, 'retained_read')
    damaged = bytearray(original); damaged[128 + 84] = 0
    read(damaged, 'retained_read_fallback')
    damaged = bytearray(original); damaged[128 + 20] ^= 1
    read(damaged, 'retained_read_fallback')
    read(bytes(256), 'retained_read_empty')
    foreign = bytearray(original)
    for offset in (0, 128):
        foreign[offset + 16] = 0xaa
        struct.pack_into('<I', foreign, offset + 80, binascii.crc32(foreign[offset:offset + 80]))
    read(foreign, 'retained_read_foreign')
