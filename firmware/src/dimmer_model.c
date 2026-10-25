#include "dimmer_model.h"

#include <limits.h>
#include <string.h>

static uint8_t normalize_level(uint8_t level) { return level == 0 ? 1 : level; }

static void cancel_off_cycle(struct dimmer_model *model)
{
    model->state.off_timer_active = false;
    model->state.auto_off_bypassed = false;
    model->off_timer_deadline_ms = 0;
}

static uint32_t next_operation(struct dimmer_model *model)
{
    if (++model->next_operation_id == 0) { model->next_operation_id = 1; }
    return model->next_operation_id;
}

void dimmer_model_init_at(struct dimmer_model *model,
    const struct dimmer_config *config, bool previous_on,
    uint8_t previous_level, uint64_t now_ms)
{
    memset(model, 0, sizeof(*model));
    model->config = *config;
    model->previous_on = previous_on;
    model->previous_level = normalize_level(previous_level);
    if(config->output_mode==DIMMER_OUTPUT_DIMMABLE){
        if(model->previous_level<config->min_level)model->previous_level=config->min_level;
        if(model->previous_level>config->max_level)model->previous_level=config->max_level;
    }
    model->state.level = model->previous_level;
    model->state.target_level = model->previous_level;
    if (config->power_on_behavior == DIMMER_POWER_ON_AWAIT_ZIGBEE) {
        model->state.restore_waiting = true;
        model->restore_deadline_ms = now_ms +
            (uint64_t)config->zigbee_restore_timeout_s * 1000U;
    } else {
        model->state.on = previous_on;
        model->state.target_on = previous_on;
    }
}

void dimmer_model_init(struct dimmer_model *model,
    const struct dimmer_config *config, bool previous_on, uint8_t previous_level)
{
    dimmer_model_init_at(model, config, previous_on, previous_level, 0);
}

void dimmer_model_cancel_restore(struct dimmer_model *model)
{
    model->state.restore_waiting = false;
    model->restore_deadline_ms = 0;
}

uint32_t dimmer_model_request(struct dimmer_model *model, bool on,
    uint8_t level, uint64_t now_ms)
{
    (void)now_ms;
    dimmer_model_cancel_restore(model);
    model->state.operation_id = next_operation(model);
    model->state.target_on = on;
    if (on) {
        model->state.target_level = model->config.output_mode == DIMMER_OUTPUT_FIXED_LEVEL
            ? model->config.fixed_level : normalize_level(level);
        if(model->config.output_mode==DIMMER_OUTPUT_DIMMABLE){
            if(model->state.target_level<model->config.min_level)model->state.target_level=model->config.min_level;
            if(model->state.target_level>model->config.max_level)model->state.target_level=model->config.max_level;
        }
    } else {
        cancel_off_cycle(model);
    }
    return model->state.operation_id;
}

bool dimmer_model_apply_effective(struct dimmer_model *model,
    uint32_t operation_id, bool on, uint8_t level)
{
    if (operation_id == 0 || operation_id != model->state.operation_id) { return false; }
    model->state.on = on;
    if (on) { model->state.level = normalize_level(level); }
    else { cancel_off_cycle(model); }
    model->previous_on = on;
    model->previous_level = model->state.level;
    return true;
}

void dimmer_model_fail(struct dimmer_model *model, uint32_t operation_id,
    enum dimmer_fault_code code)
{
    if (operation_id != model->state.operation_id || code == DIMMER_FAULT_NONE) { return; }
    model->state.fault.code = code;
    model->state.fault.active = true;
    model->state.fault.operation_id = operation_id;
    if (model->state.fault.occurrences < UINT16_MAX) { model->state.fault.occurrences++; }
}

void dimmer_model_clear_fault(struct dimmer_model *model, enum dimmer_fault_code code)
{
    if (model->state.fault.active && model->state.fault.code == code) {
        model->state.fault.active = false;
    }
}

void dimmer_model_start_off_timer(struct dimmer_model *model,
    uint64_t now_ms, uint32_t duration_ms)
{
    model->state.auto_off_bypassed = false;
    model->state.off_timer_active = duration_ms > 0;
    model->off_timer_deadline_ms = now_ms + duration_ms;
}

void dimmer_model_bypass_off_timer(struct dimmer_model *model)
{
    model->state.off_timer_active = false;
    model->state.auto_off_bypassed = true;
    model->off_timer_deadline_ms = 0;
}

uint32_t dimmer_model_timer_remaining_s(const struct dimmer_model *model,
    uint64_t now_ms)
{
    if (!model->state.off_timer_active || now_ms >= model->off_timer_deadline_ms) {
        return 0;
    }
    uint64_t remaining_ms = model->off_timer_deadline_ms - now_ms;
    return (uint32_t)((remaining_ms + 999U) / 1000U);
}

static void apply_restore_fallback(struct dimmer_model *model, uint64_t now_ms)
{
    bool on = false;
    uint8_t level = model->config.power_on_level;
    if (model->config.power_on_fallback == DIMMER_POWER_FALLBACK_ON) { on = true; }
    else if (model->config.power_on_fallback == DIMMER_POWER_FALLBACK_PREVIOUS) {
        on = model->previous_on; level = model->previous_level;
    }
    (void)dimmer_model_request(model, on, level, now_ms);
}

bool dimmer_model_tick(struct dimmer_model *model, uint64_t now_ms)
{
    if (model->state.restore_waiting && now_ms >= model->restore_deadline_ms) {
        apply_restore_fallback(model, now_ms); return true;
    }
    if (model->state.off_timer_active && now_ms >= model->off_timer_deadline_ms) {
        (void)dimmer_model_request(model, false, model->state.target_level, now_ms);
        return true;
    }
    return false;
}

bool dimmer_model_modes_supported(const struct dimmer_config *config,
    const struct dimmer_secondary_capabilities *capabilities)
{
    if (config->output_mode == DIMMER_OUTPUT_STOCK_SWITCH && !capabilities->stock_switch_mode) { return false; }
    if (config->reporting_mode == DIMMER_REPORT_ACKNOWLEDGED && !capabilities->acceptance_feedback) { return false; }
    if (config->reporting_mode == DIMMER_REPORT_PHYSICAL && !capabilities->physical_feedback) { return false; }
    return true;
}

void dimmer_model_input(struct dimmer_model *model, enum dimmer_input input,
    uint64_t now_ms)
{
    uint32_t operation;
    bool on;
    switch (input) {
    case DIMMER_INPUT_SHORT_UP:
        model->state.last_event = DIMMER_EVENT_SHORT_UP;
        on = model->config.short_press_mode == DIMMER_SHORT_SYMMETRIC_TOGGLE ? !model->state.on : true;
        operation = dimmer_model_request(model, on, model->state.level, now_ms);
        (void)dimmer_model_apply_effective(model, operation, model->state.target_on, model->state.target_level);
        break;
    case DIMMER_INPUT_SHORT_DOWN:
        model->state.last_event = DIMMER_EVENT_SHORT_DOWN;
        on = model->config.short_press_mode == DIMMER_SHORT_SYMMETRIC_TOGGLE ? !model->state.on : false;
        operation = dimmer_model_request(model, on, model->state.level, now_ms);
        (void)dimmer_model_apply_effective(model, operation, model->state.target_on, model->state.target_level);
        break;
    case DIMMER_INPUT_LONG_UP: model->state.last_event = DIMMER_EVENT_LONG_UP; model->hold_started_ms = now_ms; break;
    case DIMMER_INPUT_LONG_DOWN: model->state.last_event = DIMMER_EVENT_LONG_DOWN; model->hold_started_ms = now_ms; break;
    case DIMMER_INPUT_RELEASE_UP: model->state.last_event = DIMMER_EVENT_RELEASE_UP; model->state.last_hold_ms = (uint32_t)(now_ms - model->hold_started_ms); break;
    case DIMMER_INPUT_RELEASE_DOWN: model->state.last_event = DIMMER_EVENT_RELEASE_DOWN; model->state.last_hold_ms = (uint32_t)(now_ms - model->hold_started_ms); break;
    }
}

const struct dimmer_state *dimmer_model_state(const struct dimmer_model *model)
{
    return &model->state;
}

bool dimmer_model_sanitize_modes(struct dimmer_config *config,const struct dimmer_secondary_capabilities *caps)
{
 if(dimmer_model_modes_supported(config,caps))return false;
 config->output_mode=DIMMER_OUTPUT_DIMMABLE;
 config->reporting_mode=DIMMER_REPORT_OPTIMISTIC;
 return true;
}
