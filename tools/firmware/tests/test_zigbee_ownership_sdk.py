"""Compile the actual adapter against a synthetic SDK; execute no vendor code."""
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]

SDK = r'''
#ifndef SYNTHETIC_ZBOSS_H
#define SYNTHETIC_ZBOSS_H
#include <stdint.h>
#include <stddef.h>
typedef uint8_t zb_uint8_t;
typedef uint8_t zb_bufid_t;
typedef unsigned zb_uint_t;
typedef int zb_ret_t;
typedef void (*zb_callback_t)(zb_uint8_t);
typedef struct { uint8_t multiplicity; } zb_buf_ent_t;
typedef struct {
    uint16_t dst_addr;
    uint8_t radius, addr_mode, nonmember_radius, discovery_route;
    uint8_t security_enable, ndsu_handle, use_alias;
    uint16_t alias_src_addr;
    uint8_t alias_seq_num, extension_flags;
} zb_nlde_data_req_t;
typedef struct __attribute__((packed)) {
    uint8_t before_handle[21], msdu_handle, after_handle[5];
} zb_mcps_data_confirm_params_t;
#define RET_OK 0
#define ZB_NWK_NON_INTERNAL_NSDU_HANDLE 0
#define ZB_NWK_INTERNAL_RELAYED_UNICAST_FRAME_CONFIRM_HANDLE 0xf8
void *synthetic_tail(zb_bufid_t, size_t);
#define ZB_BUF_GET_PARAM(id, type) ((type *)synthetic_tail((id), sizeof(type)))
unsigned zb_buf_len(zb_bufid_t);
void *zb_buf_begin(zb_bufid_t);
zb_bufid_t zb_bufpool_storage_buf_to_bufid(zb_buf_ent_t *);
uint16_t zb_get_short_address(void);
void zb_nwk_forward(zb_uint8_t);
#endif
'''

HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <string.h>
#include "zboss_api.h"
static zb_buf_ent_t pool[255];
static bool busy[255];
static uint8_t packets[256][64];
static unsigned lengths[256];
static zb_nlde_data_req_t requests[256];
static zb_mcps_data_confirm_params_t confirmations[256];
static uint16_t local = 0x1234;
static unsigned next_index, confirmations_seen, copies, initials, reuses;
static uint8_t handle_seen;
static zb_callback_t queued[32];
static uint8_t queued_buffer[32];
static unsigned queue_length;
static int scheduler_result;
static bool nested, reset_in_producer, initial_in_producer;
static bool foreign_source, command_frame, short_frame, wrong_buffer, fail_allocation;
extern volatile uint32_t vimar_ownership_local_requests;
extern volatile uint32_t vimar_ownership_restored_confirmations;
void __wrap_zb_bufpool_storage_init(void);
zb_buf_ent_t *__wrap_zb_bufpool_storage_allocate(zb_uint8_t);
void __wrap_zb_bufpool_storage_free(zb_buf_ent_t *);
void __wrap_zb_buf_copy_func(zb_bufid_t, zb_bufid_t);
void *__wrap_zb_buf_initial_alloc_func(zb_bufid_t, zb_uint_t);
void *__wrap_zb_buf_reuse_func(zb_bufid_t);
void __wrap_zb_nlde_data_request(zb_uint8_t);
zb_ret_t __wrap_zb_schedule_callback(zb_callback_t, zb_uint8_t);
void __wrap_zb_nwk_handle_mcps_data_confirm(zb_uint8_t);
void __real_zb_nwk_handle_mcps_data_confirm(zb_uint8_t);
void *synthetic_tail(zb_bufid_t id, size_t size) {
    assert(id > 0);
    if (size == sizeof(zb_nlde_data_req_t)) return &requests[id];
    assert(size == sizeof(zb_mcps_data_confirm_params_t));
    return &confirmations[id];
}
unsigned zb_buf_len(zb_bufid_t id) { return lengths[id]; }
void *zb_buf_begin(zb_bufid_t id) { return packets[id]; }
uint16_t zb_get_short_address(void) { return local; }
zb_bufid_t zb_bufpool_storage_buf_to_bufid(zb_buf_ent_t *p) {
    assert(p >= pool && p < pool + 255);
    return (zb_bufid_t)(p - pool); /* Native storage conversion is zero-based. */
}
void zb_nwk_forward(zb_uint8_t id) { (void)id; }
void __real_zb_bufpool_storage_init(void) {
    memset(busy, 0, sizeof(busy)); memset(pool, 0, sizeof(pool));
}
zb_buf_ent_t *__real_zb_bufpool_storage_allocate(zb_uint8_t count) {
    if (fail_allocation) return NULL;
    assert(count > 0 && next_index + count <= 255);
    for (unsigned i = next_index; i < next_index + count; ++i) {
        assert(!busy[i]); busy[i] = true;
    }
    pool[next_index].multiplicity = count;
    return &pool[next_index];
}
void __real_zb_bufpool_storage_free(zb_buf_ent_t *p) {
    unsigned first = (unsigned)(p - pool), count = p->multiplicity;
    assert(count > 0);
    for (unsigned i = first; i < first + count; ++i) {
        assert(busy[i]); busy[i] = false;
    }
    p->multiplicity = 0;
}
void __real_zb_buf_copy_func(zb_bufid_t dst, zb_bufid_t src) {
    ++copies; memcpy(packets[dst], packets[src], sizeof(packets[dst]));
    lengths[dst] = lengths[src];
}
void *__real_zb_buf_initial_alloc_func(zb_bufid_t id, zb_uint_t size) {
    ++initials; assert(size <= sizeof(packets[id])); lengths[id] = size;
    return packets[id];
}
void *__real_zb_buf_reuse_func(zb_bufid_t id) { ++reuses; return packets[id]; }
zb_ret_t __real_zb_schedule_callback(zb_callback_t cb, zb_uint8_t id) {
    if (scheduler_result == RET_OK) {
        assert(queue_length < 32); queued[queue_length] = cb;
        queued_buffer[queue_length++] = id;
    }
    return scheduler_result;
}
static void build(zb_uint8_t id) {
    uint8_t seq = packets[id][7] + 1;
    memset(packets[id], 0x6d, sizeof(packets[id]));
    packets[id][0] = command_frame ? 1 : 0;
    packets[id][1] = 2; /* Security-marked synthetic input stays immutable. */
    packets[id][2] = 0x45; packets[id][3] = 0x23;
    uint16_t source = foreign_source ? 0x4321 : local;
    packets[id][4] = source & 255; packets[id][5] = source >> 8;
    packets[id][6] = 30; packets[id][7] = seq;
    lengths[id] = short_frame ? 7 : 48;
}
void __real_zb_nlde_data_request(zb_uint8_t id) {
    if (nested && id == 1) { nested = false; __wrap_zb_nlde_data_request(2); }
    if (reset_in_producer) {
        reset_in_producer = false; __wrap_zb_bufpool_storage_init();
        next_index = id - 1; assert(__wrap_zb_bufpool_storage_allocate(1));
    }
    if (initial_in_producer) {
        initial_in_producer = false; __wrap_zb_buf_initial_alloc_func(id, 48);
    }
    build(id);
    assert(__wrap_zb_schedule_callback(zb_nwk_forward, wrong_buffer ? id + 1 : id)
           == scheduler_result);
}
void __real_zb_nwk_handle_mcps_data_confirm(zb_uint8_t id) {
    ++confirmations_seen; handle_seen = confirmations[id].msdu_handle;
}
static void allocate(unsigned id, unsigned count) {
    next_index = id - 1;
    assert(__wrap_zb_bufpool_storage_allocate(count) == &pool[id - 1]);
}
static void produce(unsigned id) { queue_length = 0; __wrap_zb_nlde_data_request(id); }
static void confirm(unsigned id, uint8_t incoming, uint8_t expected) {
    uint8_t before_packet[64]; memcpy(before_packet, packets[id], sizeof(before_packet));
    memset(&confirmations[id], 0xa5, sizeof(confirmations[id]));
    confirmations[id].msdu_handle = incoming;
    zb_mcps_data_confirm_params_t expected_confirmation = confirmations[id];
    expected_confirmation.msdu_handle = expected;
    unsigned before = confirmations_seen;
    __wrap_zb_nwk_handle_mcps_data_confirm(id);
    assert(confirmations_seen == before + 1 && handle_seen == expected);
    assert(!memcmp(before_packet, packets[id], sizeof(before_packet)));
    assert(!memcmp(&expected_confirmation, &confirmations[id], sizeof(expected_confirmation)));
}
int main(int argc, char **argv) {
    assert(argc == 2); __wrap_zb_bufpool_storage_init(); allocate(1, 1);
    const char *mode = argv[1];
    if (!strcmp(mode, "local")) {
        produce(1); local = 0x5678; confirm(1, 0xf8, 0);
        assert(vimar_ownership_local_requests == 1);
        assert(vimar_ownership_restored_confirmations == 1);
    } else if (!strcmp(mode, "ordinary")) {
        produce(1);
        for (unsigned h = 0; h <= 255; ++h) if (h != 0xf8) confirm(1, h, h);
    } else if (!strcmp(mode, "relay")) {
        build(1); confirm(1, 0xf8, 0xf8);
    } else if (!strcmp(mode, "alias")) {
        requests[1].use_alias = 1; produce(1); confirm(1, 0xf8, 0xf8);
    } else if (!strcmp(mode, "internal")) {
        for (unsigned h = 1; h <= 255; ++h) {
            requests[1].ndsu_handle = h; produce(1); confirm(1, 0xf8, 0xf8);
        }
    } else if (!strcmp(mode, "foreign")) {
        foreign_source = true; produce(1); confirm(1, 0xf8, 0xf8);
    } else if (!strcmp(mode, "command")) {
        command_frame = true; produce(1); confirm(1, 0xf8, 0xf8);
    } else if (!strcmp(mode, "short")) {
        short_frame = true; produce(1); confirm(1, 0xf8, 0xf8);
    } else if (!strcmp(mode, "failed_enqueue")) {
        scheduler_result = -1; produce(1); assert(queue_length == 0);
        scheduler_result = RET_OK;
        assert(__wrap_zb_schedule_callback(zb_nwk_forward, 1) == RET_OK);
        confirm(1, 0xf8, 0xf8); assert(vimar_ownership_local_requests == 0);
    } else if (!strcmp(mode, "wrong_buffer")) {
        allocate(2, 1); wrong_buffer = true; produce(1); confirm(1, 0xf8, 0xf8);
    } else if (!strcmp(mode, "refresh")) {
        produce(1); uint8_t old[64]; memcpy(old, packets[1], sizeof(old));
        local = 0x5678; produce(1); local = 0x1234; confirm(1, 0xf8, 0);
        memcpy(packets[1], old, sizeof(old)); confirm(1, 0xf8, 0xf8);
    } else if (!strcmp(mode, "reset")) {
        produce(1); __wrap_zb_bufpool_storage_init(); allocate(1, 1); confirm(1, 0xf8, 0xf8);
    } else if (!strcmp(mode, "reset_during_producer")) {
        reset_in_producer = true; produce(1); confirm(1, 0xf8, 0xf8);
    } else if (!strcmp(mode, "lifetime")) {
        produce(1); __wrap_zb_bufpool_storage_free(&pool[0]); allocate(1, 1);
        confirm(1, 0xf8, 0xf8); produce(1); confirm(1, 0xf8, 0);
    } else if (!strcmp(mode, "copy")) {
        allocate(2, 1); produce(1); memcpy(packets[2], packets[1], 64); lengths[2] = 48;
        __wrap_zb_buf_copy_func(1, 2); assert(copies == 1); confirm(1, 0xf8, 0xf8);
    } else if (!strcmp(mode, "reuse")) {
        produce(1); assert(__wrap_zb_buf_reuse_func(1) == packets[1]);
        assert(reuses == 1); confirm(1, 0xf8, 0xf8);
    } else if (!strcmp(mode, "initial_alloc")) {
        produce(1); assert(__wrap_zb_buf_initial_alloc_func(1, 48) == packets[1]);
        assert(initials == 1); confirm(1, 0xf8, 0xf8);
    } else if (!strcmp(mode, "initial_during_producer")) {
        initial_in_producer = true; produce(1); confirm(1, 0xf8, 0);
    } else if (!strcmp(mode, "span")) {
        __wrap_zb_bufpool_storage_free(&pool[0]); allocate(1, 3);
        produce(1); confirm(1, 0xf8, 0); produce(2); confirm(2, 0xf8, 0xf8);
        __wrap_zb_bufpool_storage_free(&pool[0]); allocate(2, 1);
        confirm(2, 0xf8, 0xf8); produce(2); confirm(2, 0xf8, 0);
    } else if (!strcmp(mode, "callback_bridge")) {
        produce(1); queue_length = 0;
        assert(__wrap_zb_schedule_callback(__real_zb_nwk_handle_mcps_data_confirm, 1) == RET_OK);
        assert(queue_length == 1 && queued_buffer[0] == 1);
        assert(queued[0] == __wrap_zb_nwk_handle_mcps_data_confirm);
        confirmations[1].msdu_handle = 0xf8; queued[0](1);
        assert(confirmations_seen == 1 && handle_seen == 0);
        queue_length = 0; assert(__wrap_zb_schedule_callback(zb_nwk_forward, 1) == RET_OK);
        assert(queued[0] == zb_nwk_forward);
    } else if (!strcmp(mode, "nested")) {
        allocate(2, 1); nested = true; produce(1);
        assert(vimar_ownership_local_requests == 2);
        confirm(1, 0xf8, 0); confirm(2, 0xf8, 0);
    } else if (!strcmp(mode, "allocation_failure")) {
        produce(1); fail_allocation = true;
        assert(__wrap_zb_bufpool_storage_allocate(1) == NULL); confirm(1, 0xf8, 0);
    } else if (!strcmp(mode, "admission_replacement")) {
        produce(1); confirm(1, 0xf8, 0);
        requests[1].use_alias = 1; produce(1); confirm(1, 0xf8, 0xf8);
        requests[1].use_alias = 0; produce(1); confirm(1, 0xf8, 0);
        requests[1].ndsu_handle = 0xf4; produce(1); confirm(1, 0xf8, 0xf8);
        requests[1].ndsu_handle = 0; produce(1); confirm(1, 0xf8, 0);
        scheduler_result = -1; produce(1); scheduler_result = RET_OK;
        confirm(1, 0xf8, 0xf8);
    } else if (!strcmp(mode, "maximum_span")) {
        __wrap_zb_bufpool_storage_free(&pool[0]); allocate(1, 255);
        produce(1); confirm(1, 0xf8, 0);
        produce(255); confirm(255, 0xf8, 0xf8);
        __wrap_zb_bufpool_storage_free(&pool[0]); allocate(255, 1);
        confirm(255, 0xf8, 0xf8); produce(255); confirm(255, 0xf8, 0);
    } else return 2;
    return 0;
}
'''


@pytest.fixture(scope='module')
def adapter_executable(tmp_path_factory):
    directory = tmp_path_factory.mktemp('ownership-sdk')
    (directory / 'zboss_api.h').write_text(SDK)
    for name in ('zb_scheduler.h', 'zb_nwk.h', 'zb_mac.h', 'zb_nwk_mm.h', 'zb_bufpool.h'):
        (directory / name).write_text('#include "zboss_api.h"\n')
    harness = directory / 'main.c'
    harness.write_text(HARNESS)
    target = directory / 'adapter'
    subprocess.run([
        'cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=undefined', '-fno-sanitize-recover=all',
        '-I', str(directory), '-I', str(ROOT / 'firmware/src'),
        str(harness), str(ROOT / 'firmware/src/zigbee_ownership_sdk.c'),
        str(ROOT / 'firmware/src/zigbee_ownership_guard.c'), '-o', str(target),
    ], check=True, capture_output=True, text=True)
    return target


@pytest.mark.parametrize('case', [
    'local', 'ordinary', 'relay', 'alias', 'internal', 'foreign', 'command',
    'short', 'failed_enqueue', 'wrong_buffer', 'refresh', 'reset',
    'reset_during_producer', 'lifetime', 'copy', 'reuse', 'initial_alloc',
    'initial_during_producer', 'span', 'callback_bridge', 'nested',
    'allocation_failure', 'admission_replacement', 'maximum_span',
])
def test_compiled_sdk_adapter(adapter_executable, case):
    subprocess.run([str(adapter_executable), case], check=True,
                   capture_output=True, text=True)
