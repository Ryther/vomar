"""Exercise the compiled ownership policy with synthetic lifecycle events."""
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'firmware/src/zigbee_ownership_guard.c'


@pytest.fixture(scope='module')
def executable(tmp_path_factory):
    directory = tmp_path_factory.mktemp('ownership-guard')
    harness = directory / 'main.c'
    harness.write_text(r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "zigbee_ownership_guard.h"
static struct zigbee_ownership_guard guard;
static const struct zigbee_owner_packet packet = {0x1234, 0x2345, 7, true};
int main(int argc, char **argv) {
    assert(argc == 2);
    zigbee_ownership_reset(&guard);
    assert(zigbee_ownership_allocate(&guard, 6, 1));
    uint32_t token = zigbee_ownership_generation(&guard, 6);
    assert(token);
    assert(zigbee_ownership_record(&guard, 6, token, &packet, 0, false));
    if (!strcmp(argv[1], "local")) {
        uint8_t handle = 0xf8;
        assert(zigbee_ownership_confirm(&guard, 6, &packet, &handle));
        assert(handle == 0);
    } else if (!strcmp(argv[1], "ordinary")) {
        for (unsigned i = 0; i <= UINT8_MAX; ++i) {
            if (i == 0xf8) continue;
            uint8_t handle = i;
            assert(!zigbee_ownership_confirm(&guard, 6, &packet, &handle));
            assert(handle == i);
        }
    } else if (!strcmp(argv[1], "foreign")) {
        struct zigbee_owner_packet other = packet;
        other.source++;
        uint8_t handle = 0xf8;
        assert(!zigbee_ownership_confirm(&guard, 6, &other, &handle));
        assert(handle == 0xf8);
        other = packet; other.sequence++;
        assert(!zigbee_ownership_confirm(&guard, 6, &other, &handle));
        other = packet; other.destination++;
        assert(!zigbee_ownership_confirm(&guard, 6, &other, &handle));
    } else if (!strcmp(argv[1], "replacement")) {
        zigbee_ownership_invalidate(&guard, 6);
        uint8_t handle = 0xf8;
        assert(!zigbee_ownership_confirm(&guard, 6, &packet, &handle));
    } else if (!strcmp(argv[1], "lifetime")) {
        zigbee_ownership_release(&guard, 6);
        assert(zigbee_ownership_allocate(&guard, 6, 1));
        assert(zigbee_ownership_generation(&guard, 6) != token);
        assert(!zigbee_ownership_record(&guard, 6, token, &packet, 0, false));
        uint8_t handle = 0xf8;
        assert(!zigbee_ownership_confirm(&guard, 6, &packet, &handle));
    } else if (!strcmp(argv[1], "refresh")) {
        struct zigbee_owner_packet next = packet;
        for (unsigned i = 0; i < 30; ++i) {
            next.source++; next.sequence++;
            assert(zigbee_ownership_record(&guard, 6, token, &next, 0, false));
            uint8_t handle = 0xf8;
            assert(zigbee_ownership_confirm(&guard, 6, &next, &handle));
            handle = 0xf8;
            assert(!zigbee_ownership_confirm(&guard, 6, &packet, &handle));
        }
    } else if (!strcmp(argv[1], "admission")) {
        for (unsigned i = 1; i <= UINT8_MAX; ++i)
            assert(!zigbee_ownership_record(&guard, 6, token, &packet, i, false));
        assert(!zigbee_ownership_record(&guard, 6, token, &packet, 0, true));
        struct zigbee_owner_packet other = packet;
        other.is_data = false;
        assert(!zigbee_ownership_record(&guard, 6, token, &other, 0, false));
        other = packet; other.destination = 0xffff;
        assert(!zigbee_ownership_record(&guard, 6, token, &other, 0, false));
        uint8_t handle = 0xf8;
        assert(!zigbee_ownership_confirm(&guard, 6, &packet, &handle));
    } else if (!strcmp(argv[1], "span")) {
        zigbee_ownership_release(&guard, 6);
        assert(zigbee_ownership_allocate(&guard, 5, 3));
        uint8_t handle = 0xf8;
        assert(!zigbee_ownership_confirm(&guard, 6, &packet, &handle));
        assert(!zigbee_ownership_generation(&guard, 6));
        assert(!zigbee_ownership_record(&guard, 6, token, &packet, 0, false));
        uint32_t root = zigbee_ownership_generation(&guard, 5);
        zigbee_ownership_release(&guard, 6);
        assert(zigbee_ownership_generation(&guard, 5) == root);
        zigbee_ownership_release(&guard, 5);
        for (unsigned i = 5; i < 8; ++i)
            assert(!zigbee_ownership_generation(&guard, i));
    } else if (!strcmp(argv[1], "bounds")) {
        struct zigbee_ownership_guard before = guard;
        assert(!zigbee_ownership_allocate(&guard, 0, 1));
        assert(!zigbee_ownership_allocate(&guard, 255, 2));
        assert(!zigbee_ownership_allocate(&guard, 256, 1));
        assert(!zigbee_ownership_allocate(&guard, 1, 0));
        assert(!memcmp(&before, &guard, sizeof(guard)));
    } else if (!strcmp(argv[1], "exhaustion")) {
        guard.slots[6].generation = UINT32_MAX;
        zigbee_ownership_release(&guard, 6);
        assert(zigbee_ownership_allocate(&guard, 6, 1));
        assert(!zigbee_ownership_generation(&guard, 6));
        assert(!zigbee_ownership_record(&guard, 6, token, &packet, 0, false));
    } else if (!strcmp(argv[1], "reset")) {
        zigbee_ownership_reset(&guard);
        assert(!zigbee_ownership_generation(&guard, 6));
        uint8_t handle = 0xf8;
        assert(!zigbee_ownership_confirm(&guard, 6, &packet, &handle));
        assert(zigbee_ownership_allocate(&guard, 6, 1));
        assert(zigbee_ownership_generation(&guard, 6) != token);
        assert(!zigbee_ownership_record(&guard, 6, token, &packet, 0, false));
    } else if (!strcmp(argv[1], "invalid")) {
        const unsigned bad[] = {0, 256, UINT32_MAX};
        uint8_t handle = 0xf8;
        for (unsigned i = 0; i < 3; ++i) {
            assert(!zigbee_ownership_generation(&guard, bad[i]));
            assert(!zigbee_ownership_record(&guard, bad[i], token, &packet, 0, false));
            assert(!zigbee_ownership_confirm(&guard, bad[i], &packet, &handle));
            zigbee_ownership_release(&guard, bad[i]);
            zigbee_ownership_invalidate(&guard, bad[i]);
        }
        assert(!zigbee_ownership_confirm(&guard, 6, 0, &handle));
        assert(!zigbee_ownership_confirm(&guard, 6, &packet, 0));
        struct zigbee_owner_packet other = packet; other.is_data = false;
        assert(!zigbee_ownership_confirm(&guard, 6, &other, &handle));
        assert(handle == 0xf8);
    } else if (!strcmp(argv[1], "addresses")) {
        struct zigbee_owner_packet other = packet;
        other.source = other.destination = 0xfff7;
        assert(zigbee_ownership_record(&guard, 6, token, &other, 0, false));
        other.source = 0xfff8;
        assert(!zigbee_ownership_record(&guard, 6, token, &other, 0, false));
        other.source = 0x1234; other.destination = 0xfff8;
        assert(!zigbee_ownership_record(&guard, 6, token, &other, 0, false));
        assert(!zigbee_ownership_record(&guard, 6, 0, &packet, 0, false));
        assert(!zigbee_ownership_record(&guard, 6, token, 0, 0, false));
    } else return 2;
    return 0;
}
''')
    target = directory / 'policy'
    subprocess.run([
        'cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=undefined', '-fno-sanitize-recover=all',
        '-I', str(ROOT / 'firmware/src'), str(harness), str(SOURCE),
        '-o', str(target),
    ], check=True, capture_output=True, text=True)
    return target


@pytest.mark.parametrize('case', [
    'local', 'ordinary', 'foreign', 'replacement', 'lifetime', 'refresh',
    'admission', 'span', 'bounds', 'exhaustion', 'reset', 'invalid', 'addresses',
])
def test_compiled_policy(executable, case):
    subprocess.run([str(executable), case], check=True, capture_output=True, text=True)
