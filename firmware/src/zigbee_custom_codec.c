#include "zigbee_custom_codec.h"

static void put_u32(uint8_t *p, uint32_t v) { for (unsigned i = 0; i < 4; ++i) p[i] = (uint8_t)(v >> (8U * i)); }
static uint32_t get_u32(const uint8_t *p) { return p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24); }

size_t zigbee_custom_encode_event(const struct zigbee_custom_event *e, uint8_t *p, size_t n)
{
    if (!e || !p || n < ZIGBEE_CUSTOM_EVENT_SIZE) return 0;
    p[0] = e->type; p[1] = e->side; put_u32(p + 2, e->sequence_id);
    put_u32(p + 6, e->held_ms); p[10] = e->effective_on ? 1U : 0U;
    p[11] = e->effective_level; p[12] = (uint8_t)e->data; p[13] = (uint8_t)(e->data >> 8);
    return ZIGBEE_CUSTOM_EVENT_SIZE;
}

bool zigbee_custom_decode_event(const uint8_t *p, size_t n, struct zigbee_custom_event *e)
{
    if (!p || !e || n != ZIGBEE_CUSTOM_EVENT_SIZE) return false;
    e->type = p[0]; e->side = p[1]; e->sequence_id = get_u32(p + 2);
    e->held_ms = get_u32(p + 6); e->effective_on = p[10] != 0;
    e->effective_level = p[11]; e->data = p[12] | ((uint16_t)p[13] << 8);
    return e->type <= VIMAR_EVENT_FAULT && e->side <= 1;
}

size_t zigbee_custom_encode_led_override(const struct zigbee_custom_led_override *o, uint8_t *p, size_t n)
{
    if (!o || !p || n < ZIGBEE_CUSTOM_LED_OVERRIDE_SIZE || o->effect > 1) return 0;
    p[0] = o->r; p[1] = o->g; p[2] = o->b; p[3] = o->intensity; p[4] = o->effect;
    put_u32(p + 5, o->duration_ms); return ZIGBEE_CUSTOM_LED_OVERRIDE_SIZE;
}

bool zigbee_custom_decode_led_override(const uint8_t *p, size_t n, struct zigbee_custom_led_override *o)
{
    if (!p || !o || n != ZIGBEE_CUSTOM_LED_OVERRIDE_SIZE || p[4] > 1) return false;
    o->r = p[0]; o->g = p[1]; o->b = p[2]; o->intensity = p[3]; o->effect = p[4];
    o->duration_ms = get_u32(p + 5); return true;
}

bool zigbee_custom_write_config(struct dimmer_config *c, uint16_t id, uint32_t v)
{
    struct dimmer_config x = *c;
#define SET(i, f, t) case i: if ((uint32_t)(t)v != v) return false; x.f = (t)v; break
    switch (id) {
    SET(VIMAR_ATTR_INITIAL_ON_DELAY, initial_on_delay_ms, uint32_t);
    SET(VIMAR_ATTR_RISE_TRANSITION, rise_transition_ms, uint32_t);
    SET(VIMAR_ATTR_FALL_TRANSITION, fall_transition_ms, uint32_t);
    SET(VIMAR_ATTR_MIN_LEVEL, min_level, uint8_t);
    SET(VIMAR_ATTR_MAX_LEVEL, max_level, uint8_t);
    SET(VIMAR_ATTR_DOUBLE_CLICK_WINDOW, double_click_window_ms, uint16_t);
    SET(VIMAR_ATTR_LONG_PRESS_THRESHOLD, long_press_ms, uint16_t);
    SET(VIMAR_ATTR_LEVEL_STEP_PERIOD, level_step_period_ms, uint16_t);
    SET(VIMAR_ATTR_LEVEL_STEP, level_step, uint8_t);
    SET(VIMAR_ATTR_SHORT_MODE, short_press_mode, enum dimmer_short_press_mode);
    SET(VIMAR_ATTR_SINGLE_UP_ACTION, single_up_action, enum dimmer_action);
    SET(VIMAR_ATTR_SINGLE_DOWN_ACTION, single_down_action, enum dimmer_action);
    SET(VIMAR_ATTR_DOUBLE_UP_ACTION, double_up_action, enum dimmer_action);
    SET(VIMAR_ATTR_DOUBLE_DOWN_ACTION, double_down_action, enum dimmer_action);
    SET(VIMAR_ATTR_TIMER_DURATION, timer_duration_s, uint32_t);
    SET(VIMAR_ATTR_TIMER_2_DURATION, timer_2_duration_s, uint32_t);
    SET(VIMAR_ATTR_TIMER_3_DURATION, timer_3_duration_s, uint32_t);
    SET(VIMAR_ATTR_TIMER_4_DURATION, timer_4_duration_s, uint32_t);
    SET(VIMAR_ATTR_RAMP_START_LEVEL, ramp_start_level, uint8_t);
    SET(VIMAR_ATTR_RAMP_END_LEVEL, ramp_end_level, uint8_t);
    SET(VIMAR_ATTR_AUTO_OFF_MODE, auto_off_mode, enum dimmer_auto_off_mode);
    SET(VIMAR_ATTR_AUTO_OFF_DURATION, auto_off_duration_s, uint32_t);
    SET(VIMAR_ATTR_POWER_ON_BEHAVIOR, power_on_behavior, enum dimmer_power_on_behavior);
    SET(VIMAR_ATTR_POWER_ON_FALLBACK, power_on_fallback, enum dimmer_power_on_fallback);
    SET(VIMAR_ATTR_POWER_ON_LEVEL, power_on_level, uint8_t);
    SET(VIMAR_ATTR_RESTORE_TIMEOUT, zigbee_restore_timeout_s, uint16_t);
    SET(VIMAR_ATTR_OUTPUT_MODE, output_mode, enum dimmer_output_mode);
    SET(VIMAR_ATTR_REPORTING_MODE, reporting_mode, enum dimmer_reporting_mode);
    SET(VIMAR_ATTR_FIXED_LEVEL, fixed_level, uint8_t);
    SET(VIMAR_ATTR_LED_ON_R, led_on.r, uint8_t); SET(VIMAR_ATTR_LED_ON_G, led_on.g, uint8_t);
    SET(VIMAR_ATTR_LED_ON_B, led_on.b, uint8_t); SET(VIMAR_ATTR_LED_ON_INTENSITY, led_on.intensity, uint8_t);
    SET(VIMAR_ATTR_LED_OFF_R, led_off.r, uint8_t); SET(VIMAR_ATTR_LED_OFF_G, led_off.g, uint8_t);
    SET(VIMAR_ATTR_LED_OFF_B, led_off.b, uint8_t); SET(VIMAR_ATTR_LED_OFF_INTENSITY, led_off.intensity, uint8_t);
    SET(VIMAR_ATTR_LED_ON_MODE, led_on_intensity_mode, enum dimmer_led_intensity_mode);
    SET(VIMAR_ATTR_LED_ON_MIN, led_on_min_intensity, uint8_t);
    SET(VIMAR_ATTR_LED_ON_MAX, led_on_max_intensity, uint8_t);
    default: return false;
    }
#undef SET
    if (!dimmer_config_validate(&x)) return false;
    *c = x; return true;
}

bool zigbee_custom_decode_set_output(const uint8_t *payload,size_t length,bool *on,uint8_t *level)
{
    if(!payload||!on||!level||length!=2||payload[0]>1||payload[1]<1||payload[1]>254)return false;
    *on=payload[0]!=0;*level=payload[1];return true;
}
