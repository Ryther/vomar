#include "led_controller.h"
#include <string.h>

void led_controller_init(struct led_controller *controller, const struct dimmer_config *config)
{ memset(controller, 0, sizeof(*controller)); controller->config = *config; }
void led_controller_set_fault(struct led_controller *controller, bool active)
{ controller->fault_active = active; }
static void set_layer(struct led_layer *layer, const struct led_output *output,
    uint64_t now_ms, uint32_t duration_ms)
{ layer->active = true; layer->output = *output; layer->expires_ms = duration_ms ? now_ms + duration_ms : 0; }
void led_controller_set_temporary(struct led_controller *controller, const struct led_output *output, uint64_t now_ms, uint32_t duration_ms)
{ controller->temporary.active = true; controller->temporary.output = *output; controller->temporary.expires_ms = duration_ms ? now_ms + duration_ms : 0; }
void led_controller_set_override(struct led_controller *controller, const struct led_output *output, uint64_t now_ms, uint32_t duration_ms)
{ set_layer(&controller->override, output, now_ms, duration_ms); }
void led_controller_clear_override(struct led_controller *controller) { controller->override.active = false; }
static bool active(struct led_layer *layer, uint64_t now_ms)
{ if (layer->active && layer->expires_ms && now_ms >= layer->expires_ms) layer->active = false; return layer->active; }
static uint8_t scaled(const struct dimmer_config *config, uint8_t level)
{
    uint32_t span = config->led_on_max_intensity - config->led_on_min_intensity;
    uint32_t value = config->led_on_min_intensity + ((uint32_t)(level - 1) * span + 126U) / 253U;
    if (config->led_on_intensity_mode == DIMMER_LED_INTENSITY_INVERSE_LEVEL)
        value = config->led_on_max_intensity - (value - config->led_on_min_intensity);
    return (uint8_t)value;
}
struct led_output led_controller_resolve(struct led_controller *controller, bool on, uint8_t level, uint64_t now_ms)
{
    if (controller->fault_active) return (struct led_output){255, 0, 0, 100, LED_EFFECT_SLOW_BLINK};
    if (active(&controller->override, now_ms)) return controller->override.output;
    if (active(&controller->temporary, now_ms)) return controller->temporary.output;
    struct dimmer_led_profile profile = on ? controller->config.led_on : controller->config.led_off;
    struct led_output output = {profile.r, profile.g, profile.b, profile.intensity, LED_EFFECT_STATIC};
    if (on && controller->config.led_on_intensity_mode != DIMMER_LED_INTENSITY_FIXED)
        output.intensity = scaled(&controller->config, level == 0 ? 1 : level);
    return output;
}
