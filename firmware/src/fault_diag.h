#ifndef VIMAR_FAULT_DIAG_H
#define VIMAR_FAULT_DIAG_H

#include <stdbool.h>
#include <stdint.h>

#define FAULT_DIAG_BUILD_ID_SIZE 16u
#define FAULT_DIAG_RECORD_SIZE 128u
#define FAULT_DIAG_WINDOW_SIZE 256u
#define FAULT_DIAG_WINDOW_WORDS 64u
#define FAULT_DIAG_SLOT_CAUSE 0u
#define FAULT_DIAG_SLOT_ABORT 1u
#define FAULT_DIAG_MAGIC UINT32_C(0x46444941)
#define FAULT_DIAG_VERSION 1u
#define FAULT_DIAG_COMMIT UINT32_C(0x434f4d54)

enum fault_diag_kind {
    FAULT_DIAG_ASSERT = 1,
    FAULT_DIAG_ERROR = 2,
    FAULT_DIAG_ABORT = 3,
};
enum fault_diag_valid {
    FAULT_DIAG_VALID_UPTIME = 1u << 0,
    FAULT_DIAG_VALID_SOURCE = 1u << 1,
    FAULT_DIAG_VALID_LINE = 1u << 2,
    FAULT_DIAG_VALID_ERROR = 1u << 3,
    FAULT_DIAG_VALID_LR = 1u << 4,
    FAULT_DIAG_VALID_MSP = 1u << 5,
    FAULT_DIAG_VALID_PSP = 1u << 6,
    FAULT_DIAG_VALID_IPSR = 1u << 7,
    FAULT_DIAG_VALID_CONTROL = 1u << 8,
    FAULT_DIAG_VALID_GPREGRET = 1u << 9,
    FAULT_DIAG_VALID_SIGNAL = 1u << 10,
    FAULT_DIAG_VALID_SIGNAL_STATUS = 1u << 11,
    FAULT_DIAG_VALID_STAGE = 1u << 12,
    FAULT_DIAG_VALID_ROLE = 1u << 13,
    FAULT_DIAG_VALID_REPORT_KIND = 1u << 14,
    FAULT_DIAG_VALID_REPORT_LENGTH = 1u << 15,
    FAULT_DIAG_VALID_REPORT_STATUS = 1u << 16,
    FAULT_DIAG_VALID_PHASE = 1u << 17,
};

/* Native little-endian 32-bit wire layout; CRC32/IEEE covers bytes 0..119.
 * source is numeric assert file ID or checked-error site token, never a pointer.
 * Absent optional fields are zero and MUST be interpreted using valid bits.
 * No SCB fault words are sampled: stale flags are not an asserted cause. */
struct fault_diag_record {
    uint32_t magic;
    uint16_t version, length;
    uint32_t sequence, boot_sequence;
    uint8_t build_id[FAULT_DIAG_BUILD_ID_SIZE];
    uint32_t valid, kind, uptime_ms, source;
    int32_t line, error;
    uint32_t lr, msp, psp, ipsr, control, gpregret;
    uint32_t signal;
    int32_t signal_status;
    uint32_t stage, role, report_kind, report_length;
    int32_t report_status;
    uint32_t phase, reserved[2], crc, commit;
};

struct fault_diag_breadcrumb {
    uint32_t valid, uptime_ms, signal;
    int32_t signal_status;
    uint32_t stage, role, report_kind, report_length;
    int32_t report_status;
    uint32_t phase;
};

struct fault_diag_context {
    volatile uint32_t *window;
    uint8_t build_id[FAULT_DIAG_BUILD_ID_SIZE];
    uint32_t boot_sequence, sequence;
    struct fault_diag_breadcrumb breadcrumbs[2];
    volatile uint32_t breadcrumb_index;
    volatile bool busy;
    bool blocked, cause_written, abort_written;
};

/* Init never modifies the supplied 4-byte-aligned SRAM window. Any valid old
 * record, including a different build, blocks capture until acknowledge(). */
void fault_diag_init(struct fault_diag_context *, volatile uint32_t *window,
                     const uint8_t build_id[FAULT_DIAG_BUILD_ID_SIZE],
                     uint32_t boot_sequence);
/* Healthy-context updates must be serialized on this single-core target.
 * Double buffering makes capture see the previous or new complete sample. */
void fault_diag_breadcrumb(struct fault_diag_context *,
                           const struct fault_diag_breadcrumb *);
/* Caller MUST mask interrupts across each capture, saving/restoring PRIMASK.
 * This permits a bounded guard without exclusive-store retry loops. Guard
 * also rejects nested NMI/fault captures while a record is being published.
 * Return true only if this call published a record. */
bool fault_diag_capture_assert(struct fault_diag_context *, uint32_t file_id,
                               int32_t line);
bool fault_diag_capture_error(struct fault_diag_context *, uint32_t site,
                              int32_t line, int32_t rc);
bool fault_diag_capture_abort(struct fault_diag_context *, uint32_t lr,
                              uint32_t msp, uint32_t psp, uint32_t ipsr,
                              uint32_t control, uint32_t gpregret);
/* Healthy-only, no concurrent capture. Validation strictly requires supplied
 * expected identity. Old durable records require their explicit stored ID;
 * never pass the current build ID to reattribute an old capture. */
bool fault_diag_read(const volatile uint32_t *window, unsigned slot,
                     const uint8_t expected_build_id[FAULT_DIAG_BUILD_ID_SIZE],
                     struct fault_diag_record *out);
/* Healthy-only after successful durable persistence AND readback. Clears
 * commit words only. Without this call, init preserves unpersisted evidence
 * through repeated boots and intentionally suppresses later captures. */
void fault_diag_acknowledge(struct fault_diag_context *);

#endif
