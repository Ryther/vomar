"""Actual early loader hook under an independent reset model; no hardware IO."""
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'firmware/common_restore_gate/inherited_watchdog_boot.c'
FLAGS = ['CONFIG_MCUBOOT', 'CONFIG_SOC_NRF52840',
         'CONFIG_VIMAR_COMMON_RESTORE_GATE', 'CONFIG_VIMAR_INHERITED_WATCHDOG_HANDOFF']


def headers(directory):
    values = {
        'zephyr/init.h': '#define PRE_KERNEL_1 1\n#define SYS_INIT(fn,level,priority) '
                         'int (*const test_registered_gate)(void)=fn; '
                         'const int test_registered_level=level; '
                         'const int test_registered_priority=priority;\n',
        'hal/nrf_wdt.h': '#include <stdint.h>\ntypedef struct {volatile uint32_t RUNSTATUS;} NRF_WDT_Type;\n'
                          'extern NRF_WDT_Type fake_wdt;\n#define NRF_WDT (&fake_wdt)\n'
                          'void test_running_cpu_step(void);\n#define __NOP() test_running_cpu_step()\n'
                          'void test_mask_interrupts(void);\n#define __disable_irq() test_mask_interrupts()\n',
    }
    for name, text in values.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


@pytest.fixture(scope='module')
def executable(tmp_path_factory):
    directory = tmp_path_factory.mktemp('inherited_wdt')
    headers(directory)
    harness = directory / 'model.c'
    harness.write_text(r'''
#include <assert.h>
#include <setjmp.h>
#include <stdint.h>
#include <stdlib.h>
#include "hal/nrf_wdt.h"
NRF_WDT_Type fake_wdt;
extern int (*const test_registered_gate)(void);
extern const int test_registered_level,test_registered_priority;
static jmp_buf boundary;
static unsigned steps,irq_masks,image_validation,normal_main,remaining;
static int reset_enabled,force_status_zero,interrupts_masked;
void test_mask_interrupts(void) {irq_masks++;interrupts_masked=1;}
void test_running_cpu_step(void) {
    assert(interrupts_masked);assert(!image_validation&&!normal_main);
    steps++;
    if(force_status_zero)fake_wdt.RUNSTATUS=0; /* Not a real hardware reset. */
    if(reset_enabled&&--remaining==0) {
        fake_wdt.RUNSTATUS=0;interrupts_masked=0;longjmp(boundary,1);
    }
    if(steps==32)longjmp(boundary,2); /* Bounded host observation of the spin. */
}
static int boot(void) {
    int reset=setjmp(boundary);if(reset)return reset;
    assert(test_registered_gate()==0);image_validation++;normal_main++;return 0;
}
int main(int argc,char**argv) {
    assert(argc==2);assert(test_registered_level==1&&test_registered_priority==0);
    int test=atoi(argv[1]);
    if(test==0) {
        fake_wdt.RUNSTATUS=0;assert(boot()==0);
        assert(!steps&&!irq_masks&&image_validation==1&&normal_main==1);
    } else if(test==1) {
        fake_wdt.RUNSTATUS=1;reset_enabled=1;remaining=7;
        assert(boot()==1);assert(steps==7&&irq_masks==1&&!image_validation&&!normal_main);
        assert(boot()==0);assert(image_validation==1&&normal_main==1&&steps==7);
    } else if(test==2) {
        fake_wdt.RUNSTATUS=1;assert(boot()==2);
        assert(steps==32&&irq_masks==1&&!image_validation&&!normal_main);
    } else {
        fake_wdt.RUNSTATUS=1;force_status_zero=1;assert(boot()==2);
        assert(fake_wdt.RUNSTATUS==0&&steps==32&&!image_validation&&!normal_main);
    }
    return 0;
}
''')
    binary = directory / 'test-hook'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O1',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all',
                    '-I' + str(directory), *['-D' + value for value in FLAGS],
                    str(SOURCE), str(harness), '-o', str(binary)], check=True,
                   capture_output=True, text=True)
    return binary


@pytest.mark.parametrize('case', range(4))
def test_no_normal_boot_until_actual_watchdog_reset(executable, case):
    subprocess.run([str(executable), str(case)], check=True, timeout=5)


@pytest.mark.parametrize('missing', FLAGS)
def test_hook_requires_the_explicit_loader_configuration(tmp_path, missing):
    headers(tmp_path)
    result = subprocess.run(['cc', '-std=c11', '-I' + str(tmp_path),
                             *['-D' + flag for flag in FLAGS if flag != missing],
                             '-c', str(SOURCE), '-o', str(tmp_path / 'bad.o')],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert 'Inherited watchdog handoff requires the opted-in common nRF52840 loader' in result.stderr
