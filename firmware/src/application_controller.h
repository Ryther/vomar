#ifndef VIMAR_APPLICATION_CONTROLLER_H
#define VIMAR_APPLICATION_CONTROLLER_H
#include "dimmer_model.h"
#include "gesture_classifier.h"
#include "led_controller.h"
typedef void (*secondary_request_callback)(void *,uint32_t,bool,uint8_t);
typedef void (*application_gesture_callback)(void *,const struct gesture_event *);
enum application_system_event { APPLICATION_EVENT_TIMER_EXPIRED,
    APPLICATION_EVENT_RESTORE_REQUEST, APPLICATION_EVENT_STATE_CORRECTION,
    APPLICATION_EVENT_FAULT };
typedef void (*application_system_callback)(void *,enum application_system_event,uint16_t);
struct application_callbacks { secondary_request_callback secondary_request;
    application_gesture_callback gesture_event; application_system_callback system_event; void (*state_changed)(void *); };
struct application_controller { struct dimmer_model model;struct gesture_classifier gestures;struct led_controller leds;struct application_callbacks callbacks;void *context;uint64_t now_ms;struct gesture_event queued_press[GESTURE_SIDE_COUNT][2];uint8_t queued_press_count[GESTURE_SIDE_COUNT];bool hold_active[GESTURE_SIDE_COUNT];uint64_t next_level_step_ms[GESTURE_SIDE_COUNT]; bool protection_blocked, output_on, output_pending, emitting_output, ramp_target_on, ramp_cross_min; uint8_t output_level, ramp_from, ramp_to; uint64_t output_start_ms; uint32_t output_duration_ms; };
enum dimmer_request_source { DIMMER_SOURCE_ZIGBEE, DIMMER_SOURCE_PHYSICAL, DIMMER_SOURCE_ZIGBEE_LEVEL, DIMMER_SOURCE_PHYSICAL_HOLD };
void application_controller_init(struct application_controller *,const struct dimmer_config *,bool,uint8_t,const struct application_callbacks *,void *,uint64_t);
void application_controller_button_edge(struct application_controller *,enum gesture_side,bool,uint64_t);
void application_controller_command(struct application_controller *,bool,uint8_t,enum dimmer_request_source,uint64_t);
void application_controller_bypass_on(struct application_controller *,uint64_t);
void application_controller_set_protection(struct application_controller *,bool,uint64_t);
void application_controller_cancel_gestures(struct application_controller *);
void application_controller_restore_handoff(struct application_controller *,bool,uint8_t);
void application_controller_tick_input(struct application_controller *,uint64_t,bool);
void application_controller_tick(struct application_controller *,uint64_t);
void application_controller_output_failed(struct application_controller *,uint32_t,enum dimmer_fault_code);
void application_controller_feedback(struct application_controller *,uint32_t,bool,uint8_t);
const struct dimmer_state *application_controller_state(const struct application_controller *);
#endif
