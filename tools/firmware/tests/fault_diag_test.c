#include "fault_diag.h"
#include <assert.h>
#include <limits.h>
#include <setjmp.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

static const uint8_t identity[16] = {0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15};
static const uint8_t other_identity[16] = {15,14,13,12,11,10,9,8,7,6,5,4,3,2,1,0};
static uint32_t storage[66];
static volatile uint32_t *window = &storage[1];
static struct fault_diag_context context;
static jmp_buf interrupted;
static unsigned stores, stop_after = UINT_MAX, barriers;
static bool reenter;
static bool observe_publication;
static bool interrupt_breadcrumb;

static uint32_t independent_crc(const uint8_t *data, size_t size)
{
    uint32_t crc = UINT32_MAX;
    for (size_t i = 0; i < size; i++) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8; bit++)
            crc = (crc >> 1) ^ ((crc & 1u) ? UINT32_C(0xedb88320) : 0u);
    }
    return ~crc;
}

void fault_diag_test_barrier(void)
{
    barriers++;
    if (interrupt_breadcrumb) {
        interrupt_breadcrumb = false;
        assert(fault_diag_capture_assert(&context, 81, 82));
    }
}
void fault_diag_test_store(volatile uint32_t *address, uint32_t value)
{
    if (stores == stop_after) longjmp(interrupted, 1);
    stores++;
    *address = value;
    if (reenter) {
        assert(!fault_diag_capture_assert(&context, 999u, 999));
        assert(!fault_diag_capture_error(&context, 999u, 999, 999));
        assert(!fault_diag_capture_abort(&context, 999u, 999u, 999u, 999u, 999u, 999u));
    }
    if (observe_publication) {
        struct fault_diag_record record;
        /* A record cannot become visible at any earlier data store. */
        if (address == window + 31 && value == FAULT_DIAG_COMMIT) {
            assert(barriers >= 1u);
            assert(fault_diag_read(window, 0, identity, &record));
        } else {
            assert(!fault_diag_read(window, 0, identity, &record));
        }
    }
}

static void fresh(uint32_t boot)
{
    memset(storage, 0xa5, sizeof(storage));
    stores = barriers = 0;
    stop_after = UINT_MAX;
    reenter = observe_publication = interrupt_breadcrumb = false;
    fault_diag_init(&context, window, identity, boot);
    assert(stores == 0); /* Initialization must preserve evidence. */
}

static void bounds(void)
{
    assert(storage[0] == UINT32_C(0xa5a5a5a5));
    assert(storage[65] == UINT32_C(0xa5a5a5a5));
}

static void test_assert_then_abort_and_first_cause(void)
{
    struct fault_diag_record cause, abort_record;
    struct fault_diag_breadcrumb crumb = {
        .valid = FAULT_DIAG_VALID_UPTIME | FAULT_DIAG_VALID_SIGNAL |
                 FAULT_DIAG_VALID_SIGNAL_STATUS | FAULT_DIAG_VALID_STAGE |
                 FAULT_DIAG_VALID_ROLE | FAULT_DIAG_VALID_REPORT_KIND |
                 FAULT_DIAG_VALID_REPORT_LENGTH | FAULT_DIAG_VALID_REPORT_STATUS |
                 FAULT_DIAG_VALID_PHASE,
        .uptime_ms = 12345, .signal = 9, .signal_status = -7,
        .stage = 3, .role = 2, .report_kind = 4, .report_length = 70,
        .report_status = -19, .phase = 5,
    };
    fresh(42);
    assert(!fault_diag_read(window, 0, identity, &cause));
    fault_diag_breadcrumb(&context, &crumb);
    reenter = observe_publication = true;
    assert(fault_diag_capture_assert(&context, 314u, -159));
    reenter = observe_publication = false;
    assert(fault_diag_read(window, 0, identity, &cause));
    assert(cause.kind == FAULT_DIAG_ASSERT && cause.source == 314u && cause.line == -159);
    assert(cause.sequence == 1 && cause.boot_sequence == 42);
    assert(cause.valid == (crumb.valid | FAULT_DIAG_VALID_SOURCE | FAULT_DIAG_VALID_LINE));
    assert(cause.uptime_ms == 12345 && cause.signal == 9 && cause.signal_status == -7);
    assert(cause.stage == 3 && cause.role == 2 && cause.phase == 5);
    assert(cause.report_kind == 4 && cause.report_length == 70 && cause.report_status == -19);
    assert(cause.error == 0 && cause.lr == 0 && cause.msp == 0 && cause.gpregret == 0);
    assert(!fault_diag_capture_error(&context, 1, 2, -3));
    assert(!fault_diag_capture_assert(&context, 1, 2));
    crumb.uptime_ms = 23456;
    fault_diag_breadcrumb(&context, &crumb);
    assert(fault_diag_capture_abort(&context, 0x124adu, 0x20030100u,
                                    0x20030200u, 7u, 2u, 0x0102u));
    assert(fault_diag_read(window, 1, identity, &abort_record));
    assert(abort_record.kind == FAULT_DIAG_ABORT && abort_record.sequence == 2);
    assert(abort_record.boot_sequence == 42 && abort_record.uptime_ms == 23456);
    assert(abort_record.lr == 0x124adu && abort_record.msp == 0x20030100u);
    assert(abort_record.psp == 0x20030200u && abort_record.ipsr == 7u);
    assert(abort_record.control == 2u && abort_record.gpregret == 0x0102u);
    assert((abort_record.valid & (FAULT_DIAG_VALID_SOURCE | FAULT_DIAG_VALID_LINE | FAULT_DIAG_VALID_ERROR)) == 0);
    assert(!fault_diag_capture_abort(&context, 1, 2, 3, 4, 5, 6));
    struct fault_diag_record unchanged;
    assert(fault_diag_read(window, 0, identity, &unchanged));
    assert(memcmp(&cause, &unchanged, sizeof(cause)) == 0);
    assert(!fault_diag_read(window, 0, other_identity, &unchanged));
    bounds();
}

static void test_checked_error_and_abort_without_cause(void)
{
    struct fault_diag_record record;
    fresh(9);
    assert(fault_diag_capture_error(&context, 0xdecafbad, INT32_MIN, -23));
    assert(fault_diag_read(window, 0, identity, &record));
    assert(record.kind == FAULT_DIAG_ERROR && record.source == 0xdecafbad);
    assert(record.line == INT32_MIN && record.error == -23);
    assert(record.valid == (FAULT_DIAG_VALID_SOURCE | FAULT_DIAG_VALID_LINE | FAULT_DIAG_VALID_ERROR));
    assert(fault_diag_capture_abort(&context, 0x5e6fdu, 0, 0, 0, 0, 0));
    assert(fault_diag_read(window, 1, identity, &record) && record.lr == 0x5e6fdu);
    fresh(10);
    assert(fault_diag_capture_abort(&context, 0x3e361u, 1, 2, 3, 4, 5));
    assert(!fault_diag_read(window, 0, identity, &record));
    assert(fault_diag_read(window, 1, identity, &record) && record.sequence == 1);
    assert(!fault_diag_capture_assert(&context, 44, 55));
    assert(!fault_diag_capture_error(&context, 44, 55, -66));
    bounds();
}

static void test_validation_rejects_corruption_and_wrong_metadata(void)
{
    uint32_t original[64];
    struct fault_diag_record record;
    fresh(6);
    assert(fault_diag_capture_error(&context, 91, 92, -93));
    memcpy(original, (const void *)window, sizeof(original));
    /* Every bit, including metadata, build ID, CRC and commit must be covered. */
    for (unsigned word = 0; word < 32; word++) {
        for (unsigned bit = 0; bit < 32; bit++) {
            memcpy((void *)window, original, sizeof(original));
            window[word] ^= UINT32_C(1) << bit;
            assert(!fault_diag_read(window, 0, identity, &record));
        }
    }
    /* CRC-correct unknown schema/length/kind/validity is still rejected. */
    for (unsigned which = 0; which < 6; which++) {
        memcpy((void *)window, original, sizeof(original));
        if (which == 0) window[1] = (128u << 16) | 2u;
        if (which == 1) window[1] = (124u << 16) | 1u;
        if (which == 2) window[9] = 99;
        if (which == 3) window[8] |= UINT32_C(1) << 31;
        if (which == 4) window[28] = 1;
        if (which == 5) window[8] &= ~FAULT_DIAG_VALID_ERROR;
        window[30] = independent_crc((const uint8_t *)window, 120);
        assert(!fault_diag_read(window, 0, identity, &record));
    }
    memcpy((void *)window, original, sizeof(original));
    assert(!fault_diag_read(window, 2, identity, &record));
    assert(!fault_diag_read(window, 0, NULL, &record));
    bounds();
}

static void test_boots_build_identity_and_persist_acknowledgement(void)
{
    struct fault_diag_record record;
    uint32_t saved[64];
    fresh(100);
    assert(fault_diag_capture_assert(&context, 12, 34));
    assert(fault_diag_capture_abort(&context, 1, 2, 3, 4, 5, 6));
    memcpy(saved, (const void *)window, sizeof(saved));
    for (uint32_t boot = 101; boot <= 103; boot++) {
        fault_diag_init(&context, window, other_identity, boot);
        assert(!fault_diag_capture_error(&context, 88, 99, -1));
        assert(!fault_diag_capture_abort(&context, 1, 2, 3, 4, 5, 6));
        assert(memcmp(saved, (const void *)window, sizeof(saved)) == 0);
        assert(!fault_diag_read(window, 0, other_identity, &record));
        assert(fault_diag_read(window, 0, identity, &record));
        assert(record.boot_sequence == 100 && memcmp(record.build_id, identity, 16) == 0);
    }
    fault_diag_acknowledge(&context);
    assert(!fault_diag_read(window, 0, identity, &record));
    assert(!fault_diag_read(window, 1, identity, &record));
    assert(fault_diag_capture_error(&context, 55, 66, INT32_MIN));
    assert(fault_diag_read(window, 0, other_identity, &record));
    assert(record.boot_sequence == 103 && record.sequence == 3 && record.error == INT32_MIN);
    bounds();
}

static void test_all_interrupted_stores_and_reentry(bool tagged)
{
    /* Stops immediately before each store, including the final commit. */
    for (volatile unsigned cut = 0; cut < 33; cut++) {
        fresh(1);
        reenter = tagged;
        stop_after = cut;
        if (setjmp(interrupted) == 0) {
            if (tagged) (void)fault_diag_capture_error(&context, UINT32_C(0xa1ff007c), 652, -29);
            else (void)fault_diag_capture_assert(&context, 7, 8);
            assert(!"expected injected interruption");
        }
        stop_after = UINT_MAX;
        struct fault_diag_record record;
        assert(!fault_diag_read(window, 0, identity, &record));
        fault_diag_init(&context, window, identity, 2);
        assert(fault_diag_capture_assert(&context, 17, 18));
        assert(fault_diag_read(window, 0, identity, &record));
        assert(record.boot_sequence == 2 && record.source == 17);
        bounds();
    }
    for (volatile unsigned cut = 0; cut < 33; cut++) {
        fresh(3);
        assert(fault_diag_capture_error(&context, tagged ? UINT32_C(0xa1ff007c) : 123, tagged ? 652 : 456, tagged ? -29 : -789));
        assert(!fault_diag_capture_assert(&context, 116, 81));
        struct fault_diag_record cause, after;
        assert(fault_diag_read(window, 0, identity, &cause));
        stores = 0;
        reenter = tagged;
        stop_after = cut;
        if (setjmp(interrupted) == 0) {
            (void)fault_diag_capture_abort(&context, 7, 8, 9, 10, 11, 12);
            assert(!"expected injected interruption");
        }
        stop_after = UINT_MAX;
        assert(!fault_diag_read(window, 1, identity, &after));
        assert(fault_diag_read(window, 0, identity, &after));
        assert(memcmp(&cause, &after, sizeof(cause)) == 0);
        fault_diag_init(&context, window, identity, 4);
        assert(!fault_diag_capture_error(&context, 1, 2, 3));
        bounds();
    }
}

static void test_cached_snapshot_validity_and_sequence_wrap(void)
{
    struct fault_diag_record record;
    struct fault_diag_breadcrumb crumb = {
        .valid = FAULT_DIAG_VALID_UPTIME | FAULT_DIAG_VALID_SIGNAL,
        .uptime_ms = 111, .signal = 222, .signal_status = -333,
        .stage = 444, .role = 555, .report_kind = 666, .report_length = 777,
        .report_status = -888, .phase = 999,
    };
    fresh(5);
    fault_diag_breadcrumb(&context, &crumb);
    crumb.uptime_ms = 333;
    crumb.signal = 444;
    interrupt_breadcrumb = true;
    fault_diag_breadcrumb(&context, &crumb);
    assert(fault_diag_read(window, 0, identity, &record));
    assert(record.uptime_ms == 111 && record.signal == 222);
    assert(record.signal_status == 0 && record.stage == 0 && record.role == 0);
    assert(record.report_kind == 0 && record.report_length == 0 && record.report_status == 0);
    assert(record.phase == 0);
    /* Resuming the healthy writer cannot retroactively alter the first cause. */
    assert(fault_diag_capture_abort(&context, 1, 2, 3, 4, 5, 6));
    assert(fault_diag_read(window, 1, identity, &record));
    assert(record.uptime_ms == 333 && record.signal == 444);

    /* Independently encoded valid serials model an uptime-long capture count. */
    window[2] = UINT32_MAX;
    window[30] = independent_crc((const uint8_t *)window, 120);
    window[32 + 2] = 1;
    window[32 + 30] = independent_crc((const uint8_t *)(window + 32), 120);
    fault_diag_init(&context, window, identity, 6);
    fault_diag_acknowledge(&context);
    assert(fault_diag_capture_assert(&context, 1, 2));
    assert(fault_diag_read(window, 0, identity, &record) && record.sequence == 2);

    fresh(7);
    assert(fault_diag_capture_assert(&context, 1, 2));
    window[2] = UINT32_MAX;
    window[30] = independent_crc((const uint8_t *)window, 120);
    fault_diag_init(&context, window, identity, 8);
    fault_diag_acknowledge(&context);
    assert(fault_diag_capture_assert(&context, 3, 4));
    assert(fault_diag_read(window, 0, identity, &record) && record.sequence == 1);
    bounds();
}

int main(void)
{
    _Static_assert(sizeof(struct fault_diag_record) == 128, "retained slot size");
    _Static_assert(offsetof(struct fault_diag_record, crc) == 120, "CRC position");
    _Static_assert(offsetof(struct fault_diag_record, commit) == 124, "commit last");
    test_assert_then_abort_and_first_cause();
    test_checked_error_and_abort_without_cause();
    test_validation_rejects_corruption_and_wrong_metadata();
    test_boots_build_identity_and_persist_acknowledgement();
    test_all_interrupted_stores_and_reentry(false);
    test_all_interrupted_stores_and_reentry(true);
    test_cached_snapshot_validity_and_sequence_wrap();
    puts("fault diagnostics behavioral tests passed");
    return 0;
}
