"""Run real storage routing/codec/format against deterministic host IO adapters."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]


def test_ota_storage(tmp_path):
    stubs = {
        'zephyr/settings/settings.h': '''#include <stddef.h>
#include <sys/types.h>
ssize_t settings_load_one(const char *,void *,size_t);
int settings_save_one(const char *,const void *,size_t);
int settings_delete(const char *);
''',
        'zephyr/retention/bootmode.h': '''#define BOOT_MODE_TYPE_BOOTLOADER 1
int bootmode_set(int);
''',
        'zephyr/sys/reboot.h': '''#define SYS_REBOOT_COLD 0
void sys_reboot(int);
''',
    }
    for name, body in stubs.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    binary = tmp_path / 'ota_storage'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=undefined', '-I', str(tmp_path),
                    '-I', str(ROOT / 'firmware/ota'),
                    str(ROOT / 'tools/firmware/tests/ota_storage_test.c'),
                    str(ROOT / 'firmware/ota/ota_format.c'),
                    str(ROOT / 'firmware/ota/ota_transaction.c'), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
