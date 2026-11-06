/* Application-owned adapter for the pinned native ZBOSS library. */
#include <stddef.h>
#include <zboss_api.h>
#include <zb_scheduler.h>
#include <zb_nwk.h>
#include <zb_mac.h>
#include <zb_nwk_mm.h>
#include <zb_bufpool.h>

#include "zigbee_ownership_guard.h"
#if defined(CONFIG_VIMAR_ZIGBEE_DIAGNOSTIC_BATCH)
#include "zigbee_diag_batch.h"
#include "zigbee_alloc_trace.h"
#endif

#ifdef ZB_DEBUG_BUFFERS
#error "Ownership adapter requires the reviewed native buffer ABI"
#endif

_Static_assert(sizeof(zb_nlde_data_req_t) == 14, "NLDE request ABI changed");
_Static_assert(offsetof(zb_nlde_data_req_t, ndsu_handle) == 7, "NLDE handle ABI changed");
_Static_assert(offsetof(zb_nlde_data_req_t, use_alias) == 8, "NLDE alias ABI changed");
_Static_assert(sizeof(zb_mcps_data_confirm_params_t) == 27, "MCPS confirmation ABI changed");
_Static_assert(offsetof(zb_mcps_data_confirm_params_t, msdu_handle) == 21,
               "MCPS handle ABI changed");
_Static_assert(ZB_NWK_NON_INTERNAL_NSDU_HANDLE == 0, "Ordinary handle changed");
_Static_assert(ZB_NWK_INTERNAL_RELAYED_UNICAST_FRAME_CONFIRM_HANDLE == 0xf8,
               "Relay handle changed");

struct ownership_producer {
    uint32_t generation;
    zb_bufid_t buffer;
    uint8_t handle;
    bool alias;
    bool active;
};

static struct zigbee_ownership_guard ownership;
static struct ownership_producer producer;

/* Read-only debugger counters; no protocol or hardware action is attached. */
volatile uint32_t vimar_ownership_allocations;
volatile uint32_t vimar_ownership_releases;
volatile uint32_t vimar_ownership_local_requests;
volatile uint32_t vimar_ownership_confirmations;
volatile uint32_t vimar_ownership_restored_confirmations;
volatile uint32_t vimar_ownership_storage_errors;

extern void __real_zb_bufpool_storage_init(void);
extern zb_buf_ent_t *__real_zb_bufpool_storage_allocate(zb_uint8_t count);
extern void __real_zb_bufpool_storage_free(zb_buf_ent_t *buffer);
extern void __real_zb_buf_copy_func(zb_bufid_t destination, zb_bufid_t source);
extern void *__real_zb_buf_initial_alloc_func(zb_bufid_t buffer, zb_uint_t size);
extern void *__real_zb_buf_reuse_func(zb_bufid_t buffer);
extern void __real_zb_nlde_data_request(zb_uint8_t buffer);
extern void zb_nwk_forward(zb_uint8_t buffer);
extern zb_ret_t __real_zb_schedule_callback(zb_callback_t callback, zb_uint8_t buffer);
extern void __real_zb_nwk_handle_mcps_data_confirm(zb_uint8_t buffer);

void __wrap_zb_nwk_handle_mcps_data_confirm(zb_uint8_t buffer);

static bool packet_identity(zb_bufid_t buffer, struct zigbee_owner_packet *packet)
{
    if (zigbee_ownership_generation(&ownership, buffer) == 0 || zb_buf_len(buffer) < 8) {
        return false;
    }
    const uint8_t *bytes = zb_buf_begin(buffer);
    packet->source = (uint16_t)bytes[4] | ((uint16_t)bytes[5] << 8);
    packet->destination = (uint16_t)bytes[2] | ((uint16_t)bytes[3] << 8);
    packet->sequence = bytes[7];
    packet->is_data = (bytes[0] & 3u) == 0;
    return true;
}

void __wrap_zb_bufpool_storage_init(void)
{
    producer.active = false;
    zigbee_ownership_reset(&ownership);
#if defined(CONFIG_VIMAR_ZIGBEE_DIAGNOSTIC_BATCH)
    vimar_alloc_trace_pool_reset();
#endif
    __real_zb_bufpool_storage_init();
}

zb_buf_ent_t *__wrap_zb_bufpool_storage_allocate(zb_uint8_t count)
{
    zb_buf_ent_t *buffer = __real_zb_bufpool_storage_allocate(count);
#if defined(CONFIG_VIMAR_ZIGBEE_DIAGNOSTIC_BATCH)
    vimar_alloc_trace_storage_result(count, buffer == NULL ? 0 :
        (zb_bufid_t)(zb_bufpool_storage_buf_to_bufid(buffer) + 1u));
#endif
    if (buffer != NULL) {
        /* The SDK storage conversion is zero-based; public buffer IDs are not. */
        unsigned first = (unsigned)zb_bufpool_storage_buf_to_bufid(buffer) + 1u;
        if (!zigbee_ownership_allocate(&ownership, first, count)) {
            ++vimar_ownership_storage_errors;
            zigbee_ownership_reset(&ownership);
        }
        ++vimar_ownership_allocations;
    }
    return buffer;
}

void __wrap_zb_bufpool_storage_free(zb_buf_ent_t *buffer)
{
    unsigned first = (unsigned)zb_bufpool_storage_buf_to_bufid(buffer) + 1u;
#if defined(CONFIG_VIMAR_ZIGBEE_DIAGNOSTIC_BATCH)
    vimar_alloc_trace_release(first);
#endif
    zigbee_ownership_release(&ownership, first);
    ++vimar_ownership_releases;
    __real_zb_bufpool_storage_free(buffer);
}

void __wrap_zb_buf_copy_func(zb_bufid_t destination, zb_bufid_t source)
{
    zigbee_ownership_invalidate(&ownership, destination);
    __real_zb_buf_copy_func(destination, source);
}

void *__wrap_zb_buf_initial_alloc_func(zb_bufid_t buffer, zb_uint_t size)
{
    zigbee_ownership_invalidate(&ownership, buffer);
    return __real_zb_buf_initial_alloc_func(buffer, size);
}

void *__wrap_zb_buf_reuse_func(zb_bufid_t buffer)
{
    zigbee_ownership_invalidate(&ownership, buffer);
    return __real_zb_buf_reuse_func(buffer);
}

void __wrap_zb_nlde_data_request(zb_uint8_t buffer)
{
    struct ownership_producer previous = producer;
    const zb_nlde_data_req_t *request = ZB_BUF_GET_PARAM(buffer, zb_nlde_data_req_t);
    producer = (struct ownership_producer){
        .generation = zigbee_ownership_generation(&ownership, buffer),
        .buffer = buffer,
        .handle = request->ndsu_handle,
        .alias = request->use_alias != 0,
        .active = true,
    };
    zigbee_ownership_invalidate(&ownership, buffer);
    __real_zb_nlde_data_request(buffer);
    producer = previous;
}

zb_ret_t __wrap_zb_schedule_callback(zb_callback_t callback, zb_uint8_t buffer)
{
#if defined(CONFIG_VIMAR_ZIGBEE_DIAGNOSTIC_BATCH)
    if (callback == vimar_sdk_buf_diag_handle_alloc_failure) {
        if (buffer == 0) vimar_alloc_trace_failure();
        return vimar_diag_batch_schedule(buffer);
    }
#endif
    zb_callback_t scheduled = callback;
    if (callback == __real_zb_nwk_handle_mcps_data_confirm) {
        scheduled = __wrap_zb_nwk_handle_mcps_data_confirm;
    }
    zb_ret_t result = __real_zb_schedule_callback(scheduled, buffer);
    if (producer.active && producer.buffer == buffer && callback == zb_nwk_forward) {
        struct zigbee_owner_packet packet;
        if (result == RET_OK && packet_identity(buffer, &packet) &&
            packet.source == zb_get_short_address() &&
            zigbee_ownership_record(&ownership, buffer, producer.generation, &packet,
                                    producer.handle, producer.alias)) {
            ++vimar_ownership_local_requests;
        } else {
            zigbee_ownership_invalidate(&ownership, buffer);
        }
    }
    return result;
}

void __wrap_zb_nwk_handle_mcps_data_confirm(zb_uint8_t buffer)
{
    struct zigbee_owner_packet packet;
    ++vimar_ownership_confirmations;
    if (packet_identity(buffer, &packet)) {
        zb_mcps_data_confirm_params_t *confirmation =
            ZB_BUF_GET_PARAM(buffer, zb_mcps_data_confirm_params_t);
        uint8_t handle = confirmation->msdu_handle;
        if (zigbee_ownership_confirm(&ownership, buffer, &packet, &handle)) {
            confirmation->msdu_handle = handle;
            ++vimar_ownership_restored_confirmations;
        }
    }
    __real_zb_nwk_handle_mcps_data_confirm(buffer);
}
