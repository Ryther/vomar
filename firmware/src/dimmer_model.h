#ifndef VIMAR_DIMMER_MODEL_H
#define VIMAR_DIMMER_MODEL_H

#include <stdbool.h>
#include <stdint.h>
#include "dimmer_config.h"

enum dimmer_input { DIMMER_INPUT_SHORT_UP, DIMMER_INPUT_SHORT_DOWN,
    DIMMER_INPUT_LONG_UP, DIMMER_INPUT_LONG_DOWN, DIMMER_INPUT_RELEASE_UP,
    DIMMER_INPUT_RELEASE_DOWN };
enum dimmer_event { DIMMER_EVENT_NONE, DIMMER_EVENT_SHORT_UP,
    DIMMER_EVENT_SHORT_DOWN, DIMMER_EVENT_LONG_UP, DIMMER_EVENT_LONG_DOWN,
    DIMMER_EVENT_RELEASE_UP, DIMMER_EVENT_RELEASE_DOWN };
enum dimmer_fault_code { DIMMER_FAULT_NONE, DIMMER_FAULT_INVALID_SETTINGS,
    DIMMER_FAULT_UNSUPPORTED_MODE, DIMMER_FAULT_SECONDARY_UNAVAILABLE,
    DIMMER_FAULT_SECONDARY_TIMEOUT, DIMMER_FAULT_SECONDARY_REJECTED,
    DIMMER_FAULT_STATE_MISMATCH, DIMMER_FAULT_REPORT_EXHAUSTED,
    DIMMER_FAULT_OUTPUT_INHIBITED };

struct dimmer_fault { enum dimmer_fault_code code; bool active;
    uint32_t operation_id; uint16_t occurrences; };
struct dimmer_secondary_capabilities { bool acceptance_feedback;
    bool physical_feedback; bool stock_switch_mode; };
struct dimmer_state {
    bool on; uint8_t level;
    bool target_on; uint8_t target_level; uint32_t operation_id;
    enum dimmer_event last_event; uint32_t last_hold_ms;
    bool off_timer_active; bool auto_off_bypassed; bool restore_waiting;
    struct dimmer_fault fault;
};
struct dimmer_model {
    struct dimmer_config config; struct dimmer_state state;
    uint64_t hold_started_ms; uint64_t off_timer_deadline_ms;
    uint64_t restore_deadline_ms; bool previous_on; uint8_t previous_level;
    uint32_t next_operation_id;
};

void dimmer_model_init(struct dimmer_model *, const struct dimmer_config *, bool, uint8_t);
void dimmer_model_init_at(struct dimmer_model *, const struct dimmer_config *, bool, uint8_t, uint64_t);
uint32_t dimmer_model_request(struct dimmer_model *, bool, uint8_t, uint64_t);
bool dimmer_model_apply_effective(struct dimmer_model *, uint32_t, bool, uint8_t);
void dimmer_model_fail(struct dimmer_model *, uint32_t, enum dimmer_fault_code);
void dimmer_model_clear_fault(struct dimmer_model *, enum dimmer_fault_code);
bool dimmer_model_tick(struct dimmer_model *, uint64_t);
void dimmer_model_cancel_restore(struct dimmer_model *);
bool dimmer_model_sanitize_modes(struct dimmer_config *,const struct dimmer_secondary_capabilities *);
bool dimmer_model_modes_supported(const struct dimmer_config *, const struct dimmer_secondary_capabilities *);
void dimmer_model_input(struct dimmer_model *, enum dimmer_input, uint64_t);
void dimmer_model_start_off_timer(struct dimmer_model *, uint64_t, uint32_t);
void dimmer_model_bypass_off_timer(struct dimmer_model *);
uint32_t dimmer_model_timer_remaining_s(const struct dimmer_model *, uint64_t);
const struct dimmer_state *dimmer_model_state(const struct dimmer_model *);

#endif
