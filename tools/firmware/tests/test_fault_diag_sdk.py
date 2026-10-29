"""Original SDK errors reach the real retained journal without changing reset policy."""

from pathlib import Path
import struct
import subprocess
import zlib

import pytest


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "firmware/src"

# Synthetic declarations describe only the SDK boundary used by this adapter.
# No vendor source or captured device data is included in this fixture.
SDK_TYPES = """
#ifndef TEST_ZBOSS_API_H
#define TEST_ZBOSS_API_H
#include <stdint.h>
typedef uint8_t zb_uint8_t;
typedef uint16_t zb_uint16_t;
typedef int32_t zb_int_t;
typedef int32_t zb_ret_t;
typedef uint8_t zb_bool_t;
#define ZB_FALSE 0
#endif
"""
SDK_ERROR = """
#ifndef TEST_ZBOSS_API_ERROR_H
#define TEST_ZBOSS_API_ERROR_H
#define ZB_ERROR_SEVERITY_MINOR 0x01
#define ZB_ERROR_SEVERITY_MAJOR 0xfe
#define ZB_ERROR_SEVERITY_FATAL 0xff
typedef struct {
    zb_uint16_t file_id;
    zb_int_t line_number;
    void *caller_additional_info;
} zb_verify_additional_info_t;
typedef zb_bool_t (*zb_error_handler_t)(zb_uint8_t, zb_ret_t, void *);
void zb_error_register_app_handler(zb_error_handler_t);
#endif
"""

HARNESS = r"""
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/types.h>
#include "zboss_api.h"
#include "zboss_api_error.h"
#include "fault_diag_sdk.h"
#include "fault_diag.h"
#include "fault_diag_zephyr.h"
#include "build.h"

volatile uint32_t test_window[64];
static zb_error_handler_t handler;
static uint32_t primask;
static unsigned disable_calls;
static int healthy, save_error;

void zb_error_register_app_handler(zb_error_handler_t cb)
{ assert(cb != NULL); handler = cb; }
uint32_t __get_PRIMASK(void) { return primask; }
void __disable_irq(void) { primask = 1; disable_calls++; }
void __set_PRIMASK(uint32_t key) { primask = key; }
ssize_t settings_load_one(const char *key, void *data, size_t length)
{
    assert(healthy && strcmp(key, "vimar/fault_diag") == 0 && length == 256);
    (void)data;
    return -ENOENT;
}
int settings_save_one(const char *key, const void *data, size_t length)
{
    assert(healthy && strcmp(key, "vimar/fault_diag") == 0 && length == 256);
    (void)data;
    assert(save_error);
    return -EIO;
}

static void invoke(zb_uint8_t severity, zb_ret_t error, void *info)
{
    uint32_t before = primask;
    assert(handler(severity, error, info) == ZB_FALSE);
    assert(primask == before);
}

/* Hint only: never replace an existing host mapping. The final guard page
 * catches an accidental load of the caller pointer beyond the allowed span. */
static void *map_sram(void)
{
    void *hint = (void *)(uintptr_t)0x20000000;
    size_t length = 0x41000;
    void *memory = mmap(hint, length, PROT_READ | PROT_WRITE,
                        MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (memory == MAP_FAILED) exit(77);
    if (memory != hint) { assert(munmap(memory, length) == 0); exit(77); }
    assert(mprotect((char *)memory + 0x40000, 0x1000, PROT_NONE) == 0);
    return memory;
}

int main(int argc, char **argv)
{
    assert(argc == 3);
    const char *scenario = argv[1];
    primask = (uint32_t)atoi(argv[2]);
    vimar_fault_diag_sdk_register();
    assert(handler != NULL);
    if (strcmp(scenario, "not_ready") == 0) {
        invoke(0xfe, -2305, (void *)(uintptr_t)1);
        assert(disable_calls == 0);
        goto output;
    }
    if (strncmp(scenario, "blocked_", 8) == 0) {
        struct fault_diag_context previous;
        const uint8_t foreign[16] = {9};
        fault_diag_init(&previous, test_window,
            strcmp(scenario, "blocked_foreign") == 0 ? foreign : vimar_fault_build_id, 17);
        assert(fault_diag_capture_assert(&previous, 17, 19));
        save_error = 1;
    }
    healthy = 1;
    vimar_fault_diag_boot(18);
    healthy = 0;
    if (strncmp(scenario, "blocked_", 8) == 0) {
        uint32_t before[64];
        memcpy(before, (const void *)test_window, sizeof(before));
        invoke(0xfe, -2305, (void *)(uintptr_t)1);
        vimar_fault_diag_assert(116, 81);
        vimar_fault_diag_abort(0x1235, 0x20001000, 0x20002000, 0);
        assert(memcmp(before, (const void *)test_window, sizeof(before)) == 0);
        goto output;
    }
    if (strcmp(scenario, "minor_only") == 0 || strcmp(scenario, "minor_major") == 0) {
        invoke(1, -7, (void *)(uintptr_t)1);
        assert(disable_calls == 0 && test_window[31] == 0);
        if (strcmp(scenario, "minor_only") == 0) goto output;
    }

    if (strncmp(scenario, "fatal_", 6) == 0) {
        void *info = NULL;
        zb_ret_t error = -29;
        if (strcmp(scenario, "fatal_scheduler") == 0 ||
            strcmp(scenario, "fatal_buffer") == 0 ||
            strcmp(scenario, "fatal_negative_line") == 0 ||
            strcmp(scenario, "fatal_edge") == 0) {
            char *memory = map_sram();
            info = memory + (strcmp(scenario, "fatal_edge") == 0 ? 0x3fff8 : 0x100);
            /* Write only the accessible scalar fields, independently of the adapter. */
            uint16_t file = 124;
            int32_t line = 652;
            if (strcmp(scenario, "fatal_buffer") == 0) { file = 24; line = 681; error = -23; }
            if (strcmp(scenario, "fatal_negative_line") == 0) { file = 65535; line = -12; }
            if (strcmp(scenario, "fatal_edge") == 0) { file = 0; line = INT32_MIN; }
            memcpy(info, &file, 2);
            memcpy((char *)info + 4, &line, 4);
            if (strcmp(scenario, "fatal_edge") != 0)
                ((zb_verify_additional_info_t *)info)->caller_additional_info = (void *)(uintptr_t)1;
        } else if (strcmp(scenario, "fatal_misaligned") == 0) info = (void *)(uintptr_t)0x20000101;
        else if (strcmp(scenario, "fatal_below") == 0) info = (void *)(uintptr_t)0x1ffffffc;
        else if (strcmp(scenario, "fatal_short") == 0) info = (void *)(uintptr_t)0x2003fffc;
        else if (strcmp(scenario, "fatal_end") == 0) info = (void *)(uintptr_t)0x20040000;
        else if (strcmp(scenario, "fatal_above") == 0) info = (void *)(uintptr_t)0x20040004;
        else if (strcmp(scenario, "fatal_wrap") == 0) info = (void *)(UINTPTR_MAX - 3);
        else if (strcmp(scenario, "fatal_flash") == 0) info = (void *)(uintptr_t)0x26000;
        else assert(strcmp(scenario, "fatal_null") == 0);
        invoke(0xff, error, info);
    } else if (strcmp(scenario, "unknown_zero") == 0) invoke(0, -99, (void *)(uintptr_t)1);
    else if (strcmp(scenario, "unknown_severity") == 0) invoke(0x7f, -99, (void *)(uintptr_t)1);
    else if (strcmp(scenario, "signed_min") == 0) invoke(0xfe, INT32_MIN, (void *)(uintptr_t)1);
    else if (strcmp(scenario, "signed_max") == 0) invoke(0xfe, INT32_MAX, (void *)(uintptr_t)1);
    else {
        assert(strcmp(scenario, "major") == 0 || strcmp(scenario, "minor_major") == 0);
        invoke(0xfe, -2305, (void *)(uintptr_t)1);
    }
    {
        uint32_t first[32];
        memcpy(first, (const void *)test_window, sizeof(first));
        invoke(0xfe, -17, (void *)(uintptr_t)1);
        vimar_fault_diag_assert(116, 81);
        vimar_fault_diag_abort(0x1235, 0x20001000, 0x20002000, 0);
        vimar_fault_diag_abort(0xdead, 0, 0, 0);
        assert(memcmp(first, (const void *)test_window, sizeof(first)) == 0);
    }
output:
    assert(primask == (uint32_t)atoi(argv[2]));
    assert(fwrite((const void *)test_window, 1, sizeof(test_window), stdout) == sizeof(test_window));
    return 0;
}
"""


def write_headers(directory):
    headers = {
        "zboss_api.h": SDK_TYPES,
        "zboss_api_error.h": SDK_ERROR,
        "zephyr/kernel.h": """
#include <stdint.h>
#include <stdlib.h>
static inline unsigned irq_lock(void) { abort(); }
static inline void irq_unlock(unsigned key) { (void)key; abort(); }
static inline uint32_t __get_CONTROL(void) { return 0; }
uint32_t __get_PRIMASK(void);
void __disable_irq(void);
void __set_PRIMASK(uint32_t);
""",
        "zephyr/settings/settings.h": """
#include <stddef.h>
#include <sys/types.h>
ssize_t settings_load_one(const char *, void *, size_t);
int settings_save_one(const char *, const void *, size_t);
""",
        "hal/nrf_power.h": """
#define NRF_POWER ((void *)0)
static inline unsigned nrf_power_gpregret_get(void *power, unsigned index)
{ (void)power; (void)index; return 0; }
""",
        "build.h": "#include <stdint.h>\nstatic const uint8_t vimar_fault_build_id[16] = {1, 2, 3};\n",
        "force.h": "#include <stdint.h>\nextern volatile uint32_t test_window[64];\n",
    }
    for name, content in headers.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


@pytest.fixture(scope="module")
def sdk_capture(tmp_path_factory):
    directory = tmp_path_factory.mktemp("sdk-capture")
    write_headers(directory)
    harness = directory / "test.c"
    harness.write_text(HARNESS)
    executable = directory / "test"
    subprocess.run([
        "cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=undefined", "-fno-sanitize-recover=all",
        "-DCONFIG_VIMAR_FAULT_DIAGNOSTICS=1", "-DRETAINED=test_window",
        '-DVIMAR_FAULT_BUILD_ID_HEADER="build.h"', "-include", str(directory / "force.h"),
        "-I", str(directory), "-I", str(SOURCE), str(harness),
        str(SOURCE / "fault_diag_sdk.c"), str(SOURCE / "fault_diag.c"),
        str(SOURCE / "fault_diag_zephyr.c"), "-o", str(executable),
    ], check=True, capture_output=True, text=True)
    return executable


def run_capture(executable, scenario, primask):
    result = subprocess.run([str(executable), scenario, str(primask)], capture_output=True, timeout=5)
    if result.returncode == 77:
        pytest.skip("Host cannot honor the non-replacing SRAM mmap hint")
    assert result.returncode == 0, result.stderr.decode()
    assert len(result.stdout) == 256
    return result.stdout


def assert_record_integrity(slot, *, kind, sequence, boot=18, build=b"\x01\x02\x03" + b"\0" * 13):
    # Independent wire offsets and CRC, rather than the production reader.
    assert struct.unpack_from("<IHHII", slot) == (0x46444941, 1, 128, sequence, boot)
    assert slot[16:32] == build
    assert struct.unpack_from("<I", slot, 36)[0] == kind
    assert slot[112:120] == b"\0" * 8
    assert struct.unpack_from("<II", slot, 120) == (zlib.crc32(slot[:120]), 0x434F4D54)


@pytest.mark.parametrize("primask", [0, 1])
@pytest.mark.parametrize(("scenario", "source", "line", "error"), [
    ("major", 0xA0FE0000, -2147483648, -2305),
    ("minor_major", 0xA0FE0000, -2147483648, -2305),
    ("unknown_zero", 0xA0000000, -2147483648, -99),
    ("unknown_severity", 0xA07F0000, -2147483648, -99),
    ("signed_min", 0xA0FE0000, -2147483648, -2147483648),
    ("signed_max", 0xA0FE0000, -2147483648, 2147483647),
    ("fatal_scheduler", 0xA1FF007C, 652, -29),
    ("fatal_buffer", 0xA1FF0018, 681, -23),
    ("fatal_negative_line", 0xA1FFFFFF, -12, -29),
    ("fatal_edge", 0xA1FF0000, -2147483648, -29),
    *[(f"fatal_{case}", 0xA0FF0000, -2147483648, -29)
      for case in ("null", "misaligned", "below", "short", "end", "above", "wrap", "flash")],
])
def test_original_error_survives_generic_assert_and_abort(sdk_capture, scenario, source, line, error, primask):
    raw = run_capture(sdk_capture, scenario, primask)
    assert_record_integrity(raw[:128], kind=2, sequence=1)
    assert struct.unpack_from("<Iii", raw, 44) == (source, line, error)
    assert struct.unpack_from("<I", raw, 32)[0] == 0x100E
    assert_record_integrity(raw[128:], kind=3, sequence=2)
    assert struct.unpack_from("<IIIIII", raw, 128 + 56) == (0x1235, 0x20001000, 0x20002000, 0, 0, 0)


@pytest.mark.parametrize("primask", [0, 1])
@pytest.mark.parametrize("scenario", ["minor_only", "not_ready"])
def test_minor_and_not_ready_callbacks_leave_the_window_untouched(sdk_capture, scenario, primask):
    assert run_capture(sdk_capture, scenario, primask) == b"\0" * 256


@pytest.mark.parametrize("primask", [0, 1])
@pytest.mark.parametrize("scenario", ["blocked_current", "blocked_foreign"])
def test_pending_prior_evidence_blocks_sdk_error_replacement(sdk_capture, scenario, primask):
    raw = run_capture(sdk_capture, scenario, primask)
    build = b"\x09" + b"\0" * 15 if scenario == "blocked_foreign" else b"\x01\x02\x03" + b"\0" * 13
    assert_record_integrity(raw[:128], kind=1, sequence=1, boot=17, build=build)
    assert struct.unpack_from("<Ii", raw, 44) == (17, 19)
    assert raw[128:] == b"\0" * 128


def test_adapter_has_only_registration_and_ram_capture_dependencies(tmp_path):
    write_headers(tmp_path)
    obj = tmp_path / "adapter.o"
    subprocess.run([
        "cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-fno-lto",
        "-DCONFIG_VIMAR_FAULT_DIAGNOSTICS=1", "-I", str(tmp_path), "-I", str(SOURCE),
        "-c", str(SOURCE / "fault_diag_sdk.c"), "-o", str(obj),
    ], check=True, capture_output=True, text=True)
    undefined = subprocess.run(["nm", "-u", str(obj)], check=True, capture_output=True, text=True)
    assert {line.split()[-1] for line in undefined.stdout.splitlines()} == {
        "vimar_fault_diag_error", "zb_error_register_app_handler",
    }


@pytest.mark.parametrize(("header", "before", "after"), [
    ("zboss_api.h", "typedef int32_t zb_ret_t;", "typedef uint32_t zb_ret_t;"),
    ("zboss_api.h", "typedef uint8_t zb_uint8_t;", "typedef uint16_t zb_uint8_t;"),
    ("zboss_api.h", "typedef uint16_t zb_uint16_t;", "typedef uint32_t zb_uint16_t;"),
    ("zboss_api.h", "typedef int32_t zb_int_t;", "typedef int64_t zb_int_t;"),
    ("zboss_api_error.h", "    zb_uint16_t file_id;", "    zb_uint16_t prefix;\n    zb_uint16_t file_id;"),
])
def test_changed_sdk_field_abi_is_rejected_at_compile_time(tmp_path, header, before, after):
    write_headers(tmp_path)
    path = tmp_path / header
    path.write_text(path.read_text().replace(before, after))
    result = subprocess.run([
        "cc", "-std=c11", "-DCONFIG_VIMAR_FAULT_DIAGNOSTICS=1", "-I", str(tmp_path),
        "-I", str(SOURCE), "-c", str(SOURCE / "fault_diag_sdk.c"), "-o", str(tmp_path / "bad.o"),
    ], capture_output=True, text=True)
    assert result.returncode != 0
    assert "static assertion failed" in result.stderr
