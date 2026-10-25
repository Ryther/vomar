"""Real abort guard at the linker boundary; upstream defect is the RED baseline."""
from local_inputs import local_input, sdk_root
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
GUARD = ROOT / 'firmware/src/zigbee_reset_guard.c'
SDK = sdk_root() / 'ncs-zigbee/subsys/osif/zb_nrf_platform.c'


def function(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


@pytest.fixture(scope='module')
def executable(tmp_path_factory):
    directory = tmp_path_factory.mktemp('zigbee-reset-guard')
    headers = {
        'zephyr/sys/reboot.h': '#define SYS_REBOOT_COLD 1\n_Noreturn void sys_reboot(int);\n',
        'zephyr/logging/log.h': '#define LOG_MODULE_REGISTER(...)\n'
            '#define LOG_ERR(...) test_log_error()\n#define LOG_PANIC() test_panic()\n'
            'void test_log_error(void);\nvoid test_panic(void);\n',
        'zephyr/logging/log_ctrl.h': '#include <zephyr/logging/log.h>\n',
        'zephyr/toolchain.h': '#define FUNC_NORETURN _Noreturn\n',
        'zboss_api.h': '#define ZB_OSIF_SERIAL_FLUSH() test_serial_flush()\n'
            'void test_serial_flush(void);\n',
    }
    for name, content in headers.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    sdk = local_input(SDK).read_text()
    upstream = directory / 'upstream.c'
    upstream.write_text('''
#include <stdint.h>
#include <zephyr/sys/reboot.h>
#include <zephyr/logging/log.h>
#include <zboss_api.h>
#define IS_ENABLED(x) (x)
#define CONFIG_ZBOSS_RESET_ON_ASSERT 1
#define CONFIG_ZBOSS_HALT_ON_ASSERT 0
#define CONFIG_RAM_POWER_DOWN_LIBRARY 0
#define K_ERR_KERNEL_PANIC 4
#define ZVUNUSED(x) (void)(x)
typedef uint8_t zb_uint8_t;
void zb_reset(zb_uint8_t);
void nrf_power_gpregret_set(void *,unsigned,unsigned);
void k_fatal_halt(int);
void power_up_unused_ram(void);
#define NRF_POWER ((void*)0)
''' + function(sdk, 'void zb_osif_abort(void)') + '\n' +
        function(sdk, 'void zb_reset(zb_uint8_t param)'))
    caller = directory / 'caller.c'
    caller.write_text('''
void zb_osif_abort(void);
__attribute__((noinline)) void stack_abort(void) {zb_osif_abort();}
''')
    harness = directory / 'harness.c'
    harness.write_text(r'''
#include <assert.h>
#include <setjmp.h>
#include <stdlib.h>
#include <zephyr/sys/reboot.h>
static unsigned gpregret1,gpregret2,panics,errors,serial_flushes,reboots;
static jmp_buf reset;
void stack_abort(void);
void test_log_error(void){errors++;}
void test_panic(void){panics++;}
void test_serial_flush(void){serial_flushes++;}
void nrf_power_gpregret_set(void *p,unsigned index,unsigned value)
{(void)p;assert(index==0);gpregret1=value;}
void k_fatal_halt(int reason){(void)reason;abort();}
_Noreturn void sys_reboot(int mode)
{assert(mode==1);reboots++;longjmp(reset,1);}
int main(int argc,char **argv)
{
 assert(argc==3);unsigned original=(unsigned)strtoul(argv[1],0,0);
 gpregret1=original;gpregret2=0xa7;
 if(!setjmp(reset)) {
  if(atoi(argv[2])){gpregret1=1;sys_reboot(1);} /* Legitimate app recovery. */
  else stack_abort();
  abort();
 }
 assert(reboots==1);assert(gpregret2==0xa7);
 if(atoi(argv[2]))assert(gpregret1==1&&!panics&&!errors&&!serial_flushes);
 else {assert(gpregret1==original);assert(panics==1&&errors==1&&serial_flushes==1);}
 return 0;
}
''')
    objects = []
    # The upstream reset function must remain outside LTO: otherwise the
    # optimizer can inline its GPREGRET write before ld's --wrap boundary.
    for source, lto in [(upstream, False), (caller, True), (harness, True)]:
        obj = directory / (source.stem + '.o')
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
                        '-flto' if lto else '-fno-lto', '-DCONFIG_ZIGBEE_HAVE_SERIAL=1',
                        '-I' + str(directory), '-c', str(source), '-o', str(obj)],
                       check=True, capture_output=True, text=True)
        objects.append(str(obj))
    link = ['cc', '-flto', *objects]
    if GUARD.exists():
        obj = directory / 'guard.o'
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
                        '-fno-lto', '-DCONFIG_ZIGBEE_HAVE_SERIAL=1',
                        '-I' + str(directory), '-c', str(GUARD), '-o', str(obj)],
                       check=True, capture_output=True, text=True)
        link += [str(obj), '-Wl,--wrap=zb_osif_abort']
    binary = directory / 'guard-test'
    subprocess.run([*link, '-o', str(binary)], check=True, capture_output=True, text=True)
    return binary


@pytest.mark.parametrize('boot_mode', [0, 1, 0xa7])
def test_abort_keeps_boot_request_and_still_resets(executable, boot_mode):
    """Catches both SDK's spurious1 and an overly broad zero/clear workaround."""
    subprocess.run([str(executable), str(boot_mode), '0'], check=True, timeout=5)


def test_legitimate_application_recovery_keeps_bootloader_request(executable):
    subprocess.run([str(executable), '0', '1'], check=True, timeout=5)
