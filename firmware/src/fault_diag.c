#include "fault_diag.h"

#include <stddef.h>

#if defined(__BYTE_ORDER__) && __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "fault_diag retained format requires little endian"
#endif

#ifndef FAULT_DIAG_STORE_WORD
#define FAULT_DIAG_STORE_WORD(address, value) (*(address) = (value))
#endif
#ifndef FAULT_DIAG_BARRIER
#if defined(__arm__) || defined(__thumb__)
#define FAULT_DIAG_BARRIER() __asm__ volatile("dmb sy" ::: "memory")
#else
#define FAULT_DIAG_BARRIER() __asm__ volatile("" ::: "memory")
#endif
#endif

#define WORDS_PER_SLOT 32u
#define CRC_WORD 30u
#define COMMIT_WORD 31u
#define ALL_VALID ((UINT32_C(1) << 18) - 1u)
#define CAUSE_VALID (FAULT_DIAG_VALID_SOURCE | FAULT_DIAG_VALID_LINE)
#define REGISTER_VALID (FAULT_DIAG_VALID_LR | FAULT_DIAG_VALID_MSP | \
                        FAULT_DIAG_VALID_PSP | FAULT_DIAG_VALID_IPSR | \
                        FAULT_DIAG_VALID_CONTROL | FAULT_DIAG_VALID_GPREGRET)
#define BREADCRUMB_VALID (ALL_VALID & ~(CAUSE_VALID | FAULT_DIAG_VALID_ERROR | REGISTER_VALID))

union record_words {
    struct fault_diag_record record;
    uint32_t words[WORDS_PER_SLOT];
};
_Static_assert(sizeof(struct fault_diag_record) == FAULT_DIAG_RECORD_SIZE, "slot size");
_Static_assert(offsetof(struct fault_diag_record, build_id) == 16, "build identity offset");
_Static_assert(offsetof(struct fault_diag_record, crc) == CRC_WORD * 4, "CRC offset");
_Static_assert(offsetof(struct fault_diag_record, commit) == COMMIT_WORD * 4, "commit offset");

static uint32_t crc32(const union record_words *slot)
{
    const uint8_t *bytes = (const uint8_t *)slot;
    uint32_t crc = UINT32_MAX;
    for (unsigned i = 0; i < CRC_WORD * 4u; i++) {
        crc ^= bytes[i];
        for (unsigned bit = 0; bit < 8u; bit++) {
            uint32_t mask = 0u - (crc & 1u);
            crc = (crc >> 1) ^ (UINT32_C(0xedb88320) & mask);
        }
    }
    return ~crc;
}

static bool identity_matches(const uint8_t *actual, const uint8_t *expected)
{
    uint8_t difference = 0;
    for (unsigned i = 0; i < FAULT_DIAG_BUILD_ID_SIZE; i++)
        difference |= actual[i] ^ expected[i];
    return difference == 0;
}

/* Internal validation may inspect an old identity to preserve pending SRAM.
 * Public export always requires a separately supplied expected identity. */
static bool read_slot(const volatile uint32_t *window, unsigned index,
                      const uint8_t *expected, struct fault_diag_record *out)
{
    union record_words slot;
    if (index > FAULT_DIAG_SLOT_ABORT) return false;
    const volatile uint32_t *source = window + index * WORDS_PER_SLOT;
    if (source[COMMIT_WORD] != FAULT_DIAG_COMMIT) return false;
    FAULT_DIAG_BARRIER();
    for (unsigned i = 0; i < WORDS_PER_SLOT; i++) slot.words[i] = source[i];
    FAULT_DIAG_BARRIER();
    const struct fault_diag_record *r = &slot.record;
    if (source[COMMIT_WORD] != FAULT_DIAG_COMMIT || r->commit != FAULT_DIAG_COMMIT ||
        r->magic != FAULT_DIAG_MAGIC || r->version != FAULT_DIAG_VERSION ||
        r->length != FAULT_DIAG_RECORD_SIZE || r->sequence == 0 ||
        (r->valid & ~ALL_VALID) != 0 || r->reserved[0] != 0 || r->reserved[1] != 0 ||
        r->crc != crc32(&slot)) return false;
    if (expected != NULL && !identity_matches(r->build_id, expected)) return false;
    if (index == FAULT_DIAG_SLOT_CAUSE) {
        if ((r->kind != FAULT_DIAG_ASSERT && r->kind != FAULT_DIAG_ERROR) ||
            (r->valid & CAUSE_VALID) != CAUSE_VALID ||
            (r->valid & REGISTER_VALID) != 0) return false;
        if ((r->kind == FAULT_DIAG_ERROR) != ((r->valid & FAULT_DIAG_VALID_ERROR) != 0))
            return false;
    } else if (r->kind != FAULT_DIAG_ABORT ||
               (r->valid & REGISTER_VALID) != REGISTER_VALID ||
               (r->valid & (CAUSE_VALID | FAULT_DIAG_VALID_ERROR)) != 0) return false;
    *out = *r;
    return true;
}

bool fault_diag_read(const volatile uint32_t *window, unsigned index,
                     const uint8_t expected[FAULT_DIAG_BUILD_ID_SIZE],
                     struct fault_diag_record *out)
{
    if (expected == NULL || out == NULL) return false;
    return read_slot(window, index, expected, out);
}

void fault_diag_init(struct fault_diag_context *context, volatile uint32_t *window,
                     const uint8_t build_id[FAULT_DIAG_BUILD_ID_SIZE], uint32_t boot_sequence)
{
    *context = (struct fault_diag_context){0};
    context->window = window;
    context->boot_sequence = boot_sequence;
    for (unsigned i = 0; i < FAULT_DIAG_BUILD_ID_SIZE; i++) context->build_id[i] = build_id[i];
    for (unsigned index = 0; index < 2u; index++) {
        struct fault_diag_record record;
        if (read_slot(window, index, NULL, &record)) {
            /* Adjacent records may straddle sequence wrap. Unsigned serial
             * arithmetic avoids implementation-defined signed conversion. */
            uint32_t delta = record.sequence - context->sequence;
            if (!context->blocked || (delta != 0 && delta < UINT32_C(0x80000000)))
                context->sequence = record.sequence;
            context->blocked = true;
        }
    }
}

void fault_diag_breadcrumb(struct fault_diag_context *context,
                           const struct fault_diag_breadcrumb *sample)
{
    unsigned index = context->breadcrumb_index ^ 1u;
    context->breadcrumbs[index] = *sample;
    context->breadcrumbs[index].valid &= BREADCRUMB_VALID;
    FAULT_DIAG_BARRIER();
    context->breadcrumb_index = index;
}

static bool begin_capture(struct fault_diag_context *context, bool abort_record)
{
    if (context->busy) return false;
    context->busy = true;
    FAULT_DIAG_BARRIER();
    /* An NMI that completes between the guard load/store changes these flags
     * first, so this outer capture cannot replace the published first cause. */
    if (context->blocked || context->abort_written || (!abort_record && context->cause_written)) {
        context->busy = false;
        return false;
    }
    return true;
}

static void prepare_record(struct fault_diag_context *context, union record_words *slot,
                           enum fault_diag_kind kind)
{
    for (unsigned i = 0; i < WORDS_PER_SLOT; i++) slot->words[i] = 0;
    struct fault_diag_record *r = &slot->record;
    r->magic = FAULT_DIAG_MAGIC;
    r->version = FAULT_DIAG_VERSION;
    r->length = FAULT_DIAG_RECORD_SIZE;
    r->sequence = context->sequence + 1u;
    if (r->sequence == 0) r->sequence = 1;
    r->boot_sequence = context->boot_sequence;
    for (unsigned i = 0; i < FAULT_DIAG_BUILD_ID_SIZE; i++) r->build_id[i] = context->build_id[i];
    r->kind = kind;
    unsigned index = context->breadcrumb_index;
    FAULT_DIAG_BARRIER();
    const struct fault_diag_breadcrumb *b = &context->breadcrumbs[index];
    r->valid = b->valid;
    if (b->valid & FAULT_DIAG_VALID_UPTIME) r->uptime_ms = b->uptime_ms;
    if (b->valid & FAULT_DIAG_VALID_SIGNAL) r->signal = b->signal;
    if (b->valid & FAULT_DIAG_VALID_SIGNAL_STATUS) r->signal_status = b->signal_status;
    if (b->valid & FAULT_DIAG_VALID_STAGE) r->stage = b->stage;
    if (b->valid & FAULT_DIAG_VALID_ROLE) r->role = b->role;
    if (b->valid & FAULT_DIAG_VALID_REPORT_KIND) r->report_kind = b->report_kind;
    if (b->valid & FAULT_DIAG_VALID_REPORT_LENGTH) r->report_length = b->report_length;
    if (b->valid & FAULT_DIAG_VALID_REPORT_STATUS) r->report_status = b->report_status;
    if (b->valid & FAULT_DIAG_VALID_PHASE) r->phase = b->phase;
}

static void publish_record(struct fault_diag_context *context, union record_words *slot,
                           unsigned index)
{
    volatile uint32_t *destination = context->window + index * WORDS_PER_SLOT;
    slot->record.crc = crc32(slot);
    /* Invalidate first; a reset during replacement never exposes stale CRC. */
    FAULT_DIAG_STORE_WORD(&destination[COMMIT_WORD], 0u);
    FAULT_DIAG_BARRIER();
    for (unsigned i = 0; i <= CRC_WORD; i++)
        FAULT_DIAG_STORE_WORD(&destination[i], slot->words[i]);
    FAULT_DIAG_BARRIER();
    FAULT_DIAG_STORE_WORD(&destination[COMMIT_WORD], FAULT_DIAG_COMMIT);
    FAULT_DIAG_BARRIER();
    context->sequence = slot->record.sequence;
    if (index == FAULT_DIAG_SLOT_CAUSE) context->cause_written = true;
    else context->abort_written = true;
    FAULT_DIAG_BARRIER();
    context->busy = false;
}

bool fault_diag_capture_assert(struct fault_diag_context *context, uint32_t file_id, int32_t line)
{
    union record_words slot;
    if (!begin_capture(context, false)) return false;
    prepare_record(context, &slot, FAULT_DIAG_ASSERT);
    slot.record.valid |= CAUSE_VALID;
    slot.record.source = file_id;
    slot.record.line = line;
    publish_record(context, &slot, FAULT_DIAG_SLOT_CAUSE);
    return true;
}

bool fault_diag_capture_error(struct fault_diag_context *context, uint32_t site,
                              int32_t line, int32_t rc)
{
    union record_words slot;
    if (!begin_capture(context, false)) return false;
    prepare_record(context, &slot, FAULT_DIAG_ERROR);
    slot.record.valid |= CAUSE_VALID | FAULT_DIAG_VALID_ERROR;
    slot.record.source = site;
    slot.record.line = line;
    slot.record.error = rc;
    publish_record(context, &slot, FAULT_DIAG_SLOT_CAUSE);
    return true;
}

bool fault_diag_capture_abort(struct fault_diag_context *context, uint32_t lr,
                              uint32_t msp, uint32_t psp, uint32_t ipsr,
                              uint32_t control, uint32_t gpregret)
{
    union record_words slot;
    if (!begin_capture(context, true)) return false;
    prepare_record(context, &slot, FAULT_DIAG_ABORT);
    slot.record.valid |= REGISTER_VALID;
    slot.record.lr = lr;
    slot.record.msp = msp;
    slot.record.psp = psp;
    slot.record.ipsr = ipsr;
    slot.record.control = control;
    slot.record.gpregret = gpregret;
    publish_record(context, &slot, FAULT_DIAG_SLOT_ABORT);
    return true;
}

void fault_diag_acknowledge(struct fault_diag_context *context)
{
    FAULT_DIAG_STORE_WORD(&context->window[COMMIT_WORD], 0u);
    FAULT_DIAG_STORE_WORD(&context->window[WORDS_PER_SLOT + COMMIT_WORD], 0u);
    FAULT_DIAG_BARRIER();
    context->blocked = context->cause_written = context->abort_written = false;
}
