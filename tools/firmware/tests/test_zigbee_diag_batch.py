"""Compile the batching policy against synthetic boundaries; no vendor execution."""
from pathlib import Path
import subprocess

import pytest

from tools.firmware.tests.test_zigbee_ownership_sdk import SDK

ROOT = Path(__file__).resolve().parents[3]
CASES = ('duplicate', 'zero', 'one', 'wrap65535', 'wrap65536', 'wrap65537',
         'wrap131073', 'reentrant_enqueue', 'producer_during_delivery', 'irq_restore',
         'enqueue_error', 'reentrant_enqueue_error', 'foreign_fifo',
         'stats_clear_before_delivery', 'threads', 'threads_and_consumer',
         'unexpected_dataset', 'invalid_parameter', 'bounded_checkpoint',
         'timer_wrap', 'long_idle', 'alarm_admission_fatal', 'unscheduled_delivery')


@pytest.fixture(scope='module')
def executable(tmp_path_factory):
    directory = tmp_path_factory.mktemp('diag-batch')
    (directory / 'zboss_api.h').write_text(SDK.replace('#define RET_OK 0', 'typedef enum { ZB_NVRAM_ZDO_DIAGNOSTICS_DATA = 31 } zb_nvram_dataset_types_t;\n#define RET_OK 0'))
    (directory / 'zb_scheduler.h').write_text('''#include "zboss_api.h"
typedef uint32_t zb_time_t;
#define ZB_TIME_ONE_SECOND 66u
zb_time_t zb_timer_get(void);
#define ZB_TIMER_GET() zb_timer_get()
zb_ret_t zb_schedule_alarm(zb_callback_t, zb_uint8_t, zb_time_t);
''')
    (directory / 'zb_common.h').write_text('''#include "zboss_api.h"
#include <assert.h>
#define ZB_ASSERT(value) ((void)(value))
void zb_osif_abort(void);
struct synthetic_diagnostics { struct { uint16_t packet_buffer_allocate_failures; } diagnostics_info; };
extern struct synthetic_diagnostics synthetic_diagnostics;
#define ZDO_DIAGNOSTICS_CTX() synthetic_diagnostics
''')
    (directory / 'zephyr').mkdir()
    (directory / 'zephyr/irq.h').write_text('unsigned irq_lock(void);\nvoid irq_unlock(unsigned);\n')
    target = directory / 'policy'
    subprocess.run(['cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all', '-pthread',
                    '-I', str(directory), '-I', str(ROOT / 'firmware/src'),
                    str(ROOT / 'tools/firmware/tests/zigbee_diag_batch_test.c'),
                    str(ROOT / 'firmware/src/zigbee_diag_batch.c'), '-o', str(target)],
                   check=True, capture_output=True, text=True)
    return target


@pytest.mark.parametrize('case', CASES)
def test_compiled_batch_policy(executable, case):
    result = subprocess.run([str(executable), case], capture_output=True, text=True, timeout=15)
    expected = -6 if case in ('unexpected_dataset', 'invalid_parameter', 'alarm_admission_fatal', 'unscheduled_delivery') else 0
    assert result.returncode == expected, result.stdout + result.stderr
    if expected == 0: assert "RAM checkpoints" in result.stdout and "persistence calls" not in result.stdout
