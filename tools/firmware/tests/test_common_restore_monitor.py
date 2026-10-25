"""Shared P0.31 policy and fixed SRAM finalizer algorithm, synthetic host IO only."""
import ctypes as c
from pathlib import Path
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[3]
SOURCE=ROOT/'firmware/common_restore'

@pytest.fixture(scope='module')
def lib(tmp_path_factory):
    path=tmp_path_factory.mktemp('restore_monitor')/'monitor.so'
    sources=[Path(__file__).with_name('common_restore_monitor_host.c'),ROOT/'firmware/src/candidate_power_protection.c']
    for name in ['monitor.c','finalizer_core.c']:
        if (SOURCE/name).exists():sources.append(SOURCE/name)
    subprocess.run(['cc','-shared','-fPIC','-std=c11','-O1','-Wall','-Wextra','-Werror',
                    '-DCOMMON_RESTORE_HOST','-fsanitize=undefined','-fno-sanitize-recover=all',
                    '-I'+str(SOURCE),'-I'+str(ROOT/'firmware/src'),'-I'+str(ROOT/'firmware/loader_contract'),
                    *map(str,sources),'-o',str(path)],check=True,capture_output=True)
    lib=c.CDLL(str(path));lib.monitor_sample.argtypes=[c.c_uint64,c.c_int]
    return lib

def test_monitor_uses_shared_debounce_trip_and_requires_explicit_rearm_after_qualified_low(lib):
    assert lib.monitor_init()==0
    for now in range(0,601,30):lib.monitor_sample(now,0)
    assert lib.monitor_arm()==0 and lib.monitor_guard()==0
    for now in range(630,751,30):lib.monitor_sample(now,1)
    assert lib.monitor_guard()<0
    for now in range(780,1471,30):lib.monitor_sample(now,0)
    assert lib.monitor_guard()<0 # LOW cannot resume a cancelled restoration.
    assert lib.monitor_arm()==0 and lib.monitor_guard()==0

def test_cold_high_is_not_fabricated_as_a_thermal_fault_and_gaps_still_cancel(lib):
    assert lib.monitor_init()==0
    for now in range(0,121,30):lib.monitor_sample(now,1)
    assert lib.monitor_arm()==0 and lib.monitor_guard()==0
    lib.monitor_sample(250,1)
    assert lib.monitor_guard()<0 and lib.monitor_arm()<0

def test_finalizer_restores_exact_boot_and_erases_only_the_fixed_63_scratch_pages(lib):
    assert lib.final_run(0,0)==0
    assert lib.final_erases()==75 and lib.final_writes()==12288
    assert lib.final_matches()==1 and lib.final_outside()==0

@pytest.mark.parametrize('step',[1,2,12,13,100,12299,12300,12362,12363])
def test_finalizer_cancellation_stops_before_the_next_nvmc_mutation(lib,step):
    assert lib.final_run(step,0)<0
    assert lib.final_mutations()==step-1 and lib.final_outside()==0

def test_finalizer_readback_failure_stops_before_any_scratch_erase(lib):
    assert lib.final_run(0,1)<0
    assert lib.final_erases()==12 and lib.final_writes()==1 and lib.final_outside()==0
