"""Checked-error instrumentation must preserve the real SDK terminal contract."""
from local_inputs import local_input, sdk_root
from pathlib import Path
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[3]

@pytest.mark.parametrize('logging', [0, 1])
@pytest.mark.parametrize('site', [1, 2])
def test_error_is_evaluated_once_original_signed_code_and_abort_are_preserved(tmp_path, logging, site):
    sdk = local_input(sdk_root() / 'ncs-zigbee/include/zigbee/zigbee_error_handler.h')
    for name, content in {
        'zephyr/kernel.h': '', 'zboss_api.h': 'typedef int zb_ret_t;\n#define ZB_TRUE 1\n',
        'zb_errors.h': '#define RET_OK 0\n#define RET_ERROR -1\n',
        'zephyr/logging/log.h': '#define LOG_ERR(...) log_count++\n',
        'zigbee/zigbee_error_handler.h': sdk.read_text(),
        'zb_error_to_string.h': '#define zb_error_to_string_get(x) "error"\n',
    }.items():
        p = tmp_path / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content)
    source = tmp_path / 'test.c'
    source.write_text(r'''
#include <assert.h>
#include <stdint.h>
#include <setjmp.h>
static unsigned calls, captures, aborts, log_count;
static int captured_rc; static unsigned captured_site, captured_line;
static jmp_buf terminal;
void vimar_fault_diag_error(uint32_t site,int32_t line,int32_t rc)
{captures++;captured_site=site;captured_line=(unsigned)line;captured_rc=rc;}
_Noreturn void zb_osif_abort(void){aborts++;longjmp(terminal,1);}
#include "fault_diag_error_hook.h"
static int result(int value){calls++;return value;}
int main(void){
 ZB_ERROR_CHECK(result(0));assert(calls==1&&!captures&&!aborts);
 if(!setjmp(terminal)){ZB_ERROR_CHECK(result(-17));assert(0);}
 assert(calls==2&&captures==1&&aborts==1&&captured_rc==-17);
 assert(captured_site==VIMAR_DIAG_ERROR_SITE&&captured_line>0);
 if(!setjmp(terminal)){ZB_COMM_STATUS_CHECK(0);assert(0);}
 assert(captures==2&&aborts==2&&captured_rc==-1);
 assert(log_count == EXPECT_LOGS);
}
''')
    cmd = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-I'+str(tmp_path),
           '-I'+str(ROOT/'firmware/src'), '-DVIMAR_DIAG_ERROR_SITE='+str(site),
           '-DEXPECT_LOGS='+str(3 if logging else 0)]
    if logging: cmd.append('-DCONFIG_ZBOSS_ERROR_PRINT_TO_LOG=1')
    exe = tmp_path / 'test'
    subprocess.run([*cmd, str(source), '-o', str(exe)], check=True, capture_output=True, text=True)
    subprocess.run([str(exe)], check=True, timeout=5)
