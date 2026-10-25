"""Mandatory/forbidden compile boundaries for the isolated RESTORE adapter."""
from pathlib import Path
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[3]
HEADER=ROOT/'firmware/common_restore/config_guard.h'
REQUIRED=['VIMAR_COMMON_RESTORE_EXPERIMENTAL','SOC_NRF52840','ARM','ARCH_HAS_RAMFUNC_SUPPORT',
          'CODE_DATA_RELOCATION','NRF_RTC_TIMER','BT','BT_PERIPHERAL','BT_SMP','BT_FIXED_PASSKEY',
          'GPIO','FLASH','PSA_CRYPTO','PSA_WANT_ALG_SHA_256','MPU_ALLOW_FLASH_WRITE']
FORBIDDEN=['SETTINGS','NVS','BT_SETTINGS','MCUMGR','WATCHDOG','COUNTER_RTC2','NRFX_RTC2',
           'UART_CONSOLE','SHELL','USB_DEVICE_STACK','DISABLE_FLASH_PATCH']

def compile_(missing=None,extra=None):
    flags=['-DCONFIG_'+name+'=1' for name in REQUIRED if name!=missing]
    flags+=['-DCONFIG_BT_MAX_CONN=1']
    if extra:flags+=['-DCONFIG_'+extra+'=1']
    return subprocess.run(['cc','-x','c','-std=c11','-Werror','-fsyntax-only',*flags,'-'],input='#include "'+str(HEADER)+'"\n',text=True,capture_output=True)

def test_safe_isolated_config_compiles():
    result=compile_();assert result.returncode==0,result.stderr

@pytest.mark.parametrize('name',REQUIRED)
def test_missing_required_guard_is_a_build_error(name):
    assert compile_(missing=name).returncode!=0

@pytest.mark.parametrize('name',FORBIDDEN)
def test_background_storage_alternate_writers_and_conflicting_clock_are_forbidden(name):
    assert compile_(extra=name).returncode!=0
