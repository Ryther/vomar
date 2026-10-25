"""Read-only actual preflight and authenticated-only build guard checks."""
import ctypes as c
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'firmware/recovery/src'


@pytest.fixture(scope='module')
def preflight(tmp_path_factory):
    base = tmp_path_factory.mktemp('migration_preflight')
    headers = {
        'zephyr/drivers/retained_mem.h': '''#include <stdbool.h>
#include <stddef.h>
struct device {int unused;};
#define DT_NODELABEL(n) 0
#define DEVICE_DT_GET(n) ((const struct device*)1)
bool device_is_ready(const struct device*);
int retained_mem_read(const struct device*,size_t,void*,size_t);
''',
        'zephyr/settings/settings.h': '''#include <stddef.h>
#include <sys/types.h>
ssize_t settings_load_one(const char*,void*,size_t);
''',
    }
    for name, text in headers.items():
        p = base / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
    harness = base / 'preflight.c'
    harness.write_text(r'''
#include "research_handoff.h"
#include <zephyr/drivers/retained_mem.h>
#include <assert.h>
#include <errno.h>
#include <string.h>
#include <sys/types.h>
int recovery_migration_preflight(void);
static int journal_result,marker_error,record_error,ready;
static unsigned writes,reads;
static uint8_t marker,record[RESEARCH_PROTECTED_HANDOFF_SIZE];
bool device_is_ready(const struct device*d){(void)d;return ready;}
int retained_mem_read(const struct device*d,size_t off,void*p,size_t n)
{(void)d;assert(!off&&n==1);reads++;if(marker_error)return marker_error;*(uint8_t*)p=marker;return 0;}
ssize_t settings_load_one(const char*key,void*p,size_t n)
{
 reads++;
 if(!strcmp(key,"vimar/ota"))return journal_result;
 assert(!strcmp(key,"vimar/handoff")&&n==sizeof(record));
 if(record_error)return record_error;
 memcpy(p,record,n);return n;
}
static int save_record(void*c,const uint8_t*p,size_t n)
{(void)c;assert(n==sizeof(record));writes++;memcpy(record,p,n);return 0;}
static int set_marker(void*c,uint8_t v){(void)c;writes++;marker=v;return 0;}
int execute(int journal,unsigned mark,int marker_rc,int corrupt,int record_rc,int available)
{
 const struct research_handoff_io io={.save=save_record,.set_marker=set_marker};
 const struct research_protected_handoff handoff={.level=123,.trips=7,.armed=true};
 assert(!research_handoff_prepare_protected(&io,&handoff));
 marker=(uint8_t)mark;journal_result=journal;marker_error=marker_rc;record_error=record_rc;ready=available;
 if(corrupt)record[16]^=1;
 writes=reads=0;int rc=recovery_migration_preflight();assert(!writes&&marker==(uint8_t)mark);
 return rc;
}
''')
    lib = base / 'preflight.so'
    subprocess.run(['cc', '-shared', '-fPIC', '-std=c11', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=undefined', '-fno-sanitize-recover=all', '-I' + str(base),
        '-I' + str(ROOT / 'firmware/research/src'), str(harness),
        str(SOURCE / 'recovery_migration_preflight_zephyr.c'),
        str(ROOT / 'firmware/research/src/research_handoff.c'), '-o', str(lib)], check=True)
    return c.CDLL(str(lib))


@pytest.mark.parametrize('args,expected', [
    ((0, 0, 0, 0, 0, 1), 0), ((-2, 0, 0, 0, 0, 1), 0),
    ((0, 0xa8, 0, 0, 0, 1), 0), ((0, 0xa8, 0, 1, 0, 1), -22),
    ((1, 0, 0, 0, 0, 1), -16), ((-5, 0, 0, 0, 0, 1), -5),
    ((0, 0, -5, 0, 0, 1), -5), ((0, 0xa7, 0, 0, 0, 1), -93),
    ((0, 0x12, 0, 0, 0, 1), -22), ((0, 0xa8, 0, 0, -5, 1), -5),
    ((0, 0xa8, 0, 0, 19, 1), -22), ((0, 0, 0, 0, 0, 0), -19),
])
def test_pending_journal_and_invalid_handoff_refuse_without_consumption(preflight, args, expected):
    assert preflight.execute(*args) == expected


REQUIRED = ['VIMAR_P031_PROTECTION', 'VIMAR_RECOVERY_BUTTON_EXIT', 'VIMAR_OTA_INSTALLER',
    'MCUMGR_TRANSPORT_BT', 'MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN',
    'MCUMGR_SMP_COMMAND_STATUS_HOOKS', 'MCUMGR_MGMT_NOTIFICATION_HOOKS',
    'MCUMGR_GRP_IMG_STATUS_HOOKS', 'MCUMGR_GRP_IMG_MUTEX', 'MCUMGR_GRP_OS_RESET_HOOK']
FORBIDDEN = ['MCUMGR_TRANSPORT_UART', 'MCUMGR_TRANSPORT_RAW_UART', 'MCUMGR_TRANSPORT_UART_ASYNC',
    'MCUMGR_TRANSPORT_UDP', 'MCUMGR_TRANSPORT_SHELL', 'MCUMGR_TRANSPORT_LORAWAN',
    'MCUMGR_TRANSPORT_DUMMY', 'MCUMGR_TRANSPORT_RAW_DUMMY',
    'MCUMGR_TRANSPORT_BT_PERM_RW', 'MCUMGR_TRANSPORT_BT_PERM_RW_ENCRYPT', 'IMG_ENABLE_IMAGE_CHECK']


@pytest.mark.parametrize('remove,add', [(None, None)] + [(name, None) for name in REQUIRED] +
                         [(None, name) for name in FORBIDDEN])
def test_migration_build_guard_requires_authenticated_bluetooth_and_real_status_hooks(remove, add):
    flags = ['-DCONFIG_VIMAR_RECOVERY_MIGRATION_EXEC=1']
    flags += ['-DCONFIG_' + name + '=1' for name in REQUIRED if name != remove]
    if add: flags += ['-DCONFIG_' + add + '=1']
    result = subprocess.run(['cc', '-E', '-x', 'c', '-I' + str(SOURCE), *flags, '-'],
        input='#include "recovery_migration_config.h"\n', capture_output=True, text=True)
    assert (result.returncode == 0) == (remove is None and add is None), result.stderr
    if result.returncode:
        assert 'Migration execution' in result.stderr and 'No such file' not in result.stderr
