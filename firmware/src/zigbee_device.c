#include "zigbee_device.h"

#include <errno.h>

#include "application_controller.h"
#include "app_settings_backend.h"
#include "platform_io.h"
#include "phase_cut_control.h"
#include "vimar_power_protection.h"
#include "boot_trace.h"
#include "fault_diag_zephyr.h"
#include "fault_diag_sdk.h"
#if defined(CONFIG_VIMAR_ZIGBEE_OTA)
#include "zigbee_ota.h"
#endif
#include "zb_dimmable_light.h"
#include "zb_vimar_custom.h"
#include "zigbee_report_policy.h"
#include "connection_pairing.h"
#include "connection_intent.h"

#include <zephyr/logging/log.h>
#include <zephyr/app_version.h>
#include <dk_buttons_and_leds.h>
#include <zb_nrf_platform.h>
#include <zboss_api.h>
#include <zboss_api_addons.h>
#include <zigbee/zigbee_app_utils.h>
#include <zigbee/zigbee_error_handler.h>

#if defined(CONFIG_VIMAR_HARDWARE)
#include <hal/nrf_ficr.h>
#include "vimar_identity.h"
#endif

#define VIMAR_ZIGBEE_ENDPOINT 1
#define VIMAR_MANUFACTURER "OpenVimar"
#if defined(CONFIG_VIMAR_HARDWARE)
#define VIMAR_MODEL "Vimar30805"
#else
#define VIMAR_MODEL "Vimar30805-DK"
#endif
#define STATE_SNAPSHOT_INTERVAL_MS 60000
#define APPLICATION_TICK_INTERVAL_MS 25
#define LED_RUNTIME_REPORT_INTERVAL_MS 250U

LOG_MODULE_REGISTER(vimar_zigbee, LOG_LEVEL_INF);

static struct connection_pairing connection_pairing;
static bool connection_selecting,pairing_expired,pairing_stop_pending;
static uint64_t connection_selector_since;
static int initial_connection_intent;

void zigbee_device_connection_selector(bool active,uint64_t since_ms)
{connection_selecting=active;connection_selector_since=since_ms;}

static void cancel_pairing(zb_bufid_t buffer)
{
    pairing_stop_pending=false;
    /* bdb_cancel_joining takes ownership and reports cancellation by signal. */
    bdb_cancel_joining(buffer);
}

static void connection_pairing_poll(uint64_t now)
{
    if(connection_pairing_tick(&connection_pairing,now)) {
        pairing_expired=true;pairing_stop_pending=true;
        zigbee_network_rejoin_abort();
        LOG_INF("Zigbee pairing window expired");
    }
    if(pairing_stop_pending) {
        if(zb_buf_get_out_delayed(cancel_pairing)==RET_OK)pairing_stop_pending=false;
    }
}

static bool pairing_signal_requires_window(zb_zdo_app_signal_type_t signal)
{
    switch(signal){
    case ZB_BDB_SIGNAL_STEERING:
    case ZB_BDB_SIGNAL_STEERING_CANCELLED:
    case ZB_BDB_SIGNAL_TC_REJOIN_DONE:
    case ZB_ZDO_SIGNAL_LEAVE:return true;
    default:return false;
    }
}

#if defined(CONFIG_VIMAR_FAULT_DIAGNOSTICS)
static void vimar_diag_zboss_assert(zb_uint16_t file_id,zb_int_t line)
{vimar_fault_diag_assert(file_id,(int32_t)line);}

/* Capture each locally constructed ZCL send before entering the stack. The
 * result is an immediate submission status; completion is a separate phase. */
static zb_ret_t diagnostic_finish_packet(zb_bufid_t buffer,zb_uint8_t *ptr,
    const zb_addr_u *address,zb_uint8_t mode,zb_uint8_t dst,zb_uint8_t ep,
    zb_uint16_t profile,zb_uint16_t cluster,zb_callback_t callback)
{
    const zb_uint8_t *start=zb_buf_begin(buffer);
    uint32_t length=(uint32_t)(ptr-start);
    uint32_t kind=((uint32_t)cluster<<8)|(length>=3?start[2]:0xffu);
    vimar_fault_diag_report(kind,length,INT32_MIN);
    zb_ret_t rc=zb_zcl_finish_and_send_packet(buffer,ptr,address,mode,dst,ep,profile,cluster,callback);
    vimar_fault_diag_report(kind,length,rc);
    return rc;
}
#define zb_zcl_finish_and_send_packet diagnostic_finish_packet
#endif

BUILD_ASSERT(sizeof(APP_VERSION_STRING) - 1U <= 16U,
    "APP_VERSION_STRING must fit Basic SWBuildID");

struct zigbee_context {
    zb_zcl_basic_attrs_ext_t basic;
    zb_zcl_identify_attrs_t identify;
    zb_zcl_scenes_attrs_t scenes;
    zb_zcl_groups_attrs_t groups;
    zb_zcl_on_off_attrs_t on_off;
    zb_zcl_level_control_attrs_t level;
    uint16_t schema_version;
    uint32_t capabilities;
    uint32_t initial_on_delay_ms, rise_transition_ms, fall_transition_ms;
    uint8_t min_level, max_level;
    uint16_t double_click_window_ms;
    uint16_t long_press_ms;
    uint16_t level_step_period_ms;
    uint8_t level_step;
    uint8_t short_mode;
    uint8_t single_up_action, single_down_action;
    uint8_t double_up_action, double_down_action;
    uint32_t timer_duration_s, timer_2_duration_s, timer_3_duration_s, timer_4_duration_s;
    uint8_t ramp_start_level, ramp_end_level;
    uint8_t auto_off_mode;
    uint32_t auto_off_duration_s;
    uint8_t power_on_behavior, power_on_fallback, power_on_level;
    uint16_t restore_timeout_s;
    uint8_t output_mode;
    uint8_t reporting_mode;
    uint8_t fixed_level;
    uint8_t phase_cut_mode;
    uint8_t led_on_r, led_on_g, led_on_b, led_on_intensity;
    uint8_t led_off_r, led_off_g, led_off_b, led_off_intensity;
    uint8_t led_on_mode, led_on_min, led_on_max;
    /* Controller-resolved command, not measured physical LED output. */
    uint8_t led_runtime_r, led_runtime_g, led_runtime_b, led_runtime_intensity;
    uint8_t led_runtime_effect;
    zb_bool_t led_override_active;
    zb_bool_t applied_output_on, transition_active;
    uint8_t applied_output_level;
    zb_bool_t target_on;
    uint8_t target_level;
    zb_bool_t timer_active;
    zb_bool_t restore_pending;
    uint8_t fault_code;
    zb_bool_t auto_off_bypassed;
    uint32_t timer_remaining_s;
    zb_bool_t p031_enabled;
    uint8_t p031_raw_level;
    zb_bool_t p031_sample_valid;
    zb_bool_t p031_low_qualified;
    zb_bool_t p031_signal_inhibit;
    zb_bool_t p031_output_blocked;
    zb_bool_t p031_notification;
    uint32_t p031_trip_count;
    uint32_t p031_max_sample_gap_ms;
    uint32_t p031_monitor_uptime_s;
    uint8_t last_boot_reason;
    uint32_t last_reset_flags;
    uint32_t boot_sequence;
    uint8_t ota_contract[OTA_RUNTIME_CONTRACT_ZCL_SIZE];
    uint32_t fault_diag_status;
    uint8_t fault_diag[8][33];

};

/* One standalone READ response: 3-byte ZCL header + 4-byte record + string.
 * Fits the SDK's conservative66-byte budget; no fragmentation/ABI flags. */
BUILD_ASSERT(3u+4u+OTA_RUNTIME_CONTRACT_ZCL_SIZE<=ZB_ZCL_HI_MAX_PAYLOAD_SIZE);
static struct zigbee_context context;
static uint32_t ota_contract_sample;
static uint64_t ota_contract_updated_ms;
static struct application_controller controller;
static struct zigbee_report_policy report_policy;
static struct zigbee_custom_event event_queue[8];
static uint8_t event_head, event_count;
static bool event_send_active;
static bool app_factory_reset_done;
static bool timer_report_active;
static uint64_t last_timer_report_ms;
static uint64_t last_output_report_ms;
static bool output_report_pending;
static bool led_report_pending;
static uint64_t last_led_report_ms;


static zb_uint8_t custom_received_commands[] = {
    VIMAR_COMMAND_CLEAR_LED_OVERRIDE, VIMAR_COMMAND_APPLY_LED_OVERRIDE,
    VIMAR_COMMAND_REQUEST_SNAPSHOT,
    VIMAR_COMMAND_BYPASS_ON, VIMAR_COMMAND_ENTER_RECOVERY, VIMAR_COMMAND_SET_OUTPUT,
    VIMAR_COMMAND_SET_PHASE_CUT,
};
static zb_uint8_t custom_generated_commands[] = { VIMAR_COMMAND_EVENT };
static zb_discover_cmd_list_t custom_server_commands = {
    sizeof(custom_generated_commands), custom_generated_commands,
    sizeof(custom_received_commands), custom_received_commands,
};

static void request_snapshot(void);
static void send_next_event(zb_bufid_t buffer);

static uint32_t custom_value(zb_uint16_t attr_id, const zb_uint8_t *value)
{
    if (attr_id == VIMAR_ATTR_INITIAL_ON_DELAY ||
        attr_id == VIMAR_ATTR_RISE_TRANSITION ||
        attr_id == VIMAR_ATTR_FALL_TRANSITION ||
        attr_id == VIMAR_ATTR_TIMER_DURATION ||
        attr_id == VIMAR_ATTR_TIMER_2_DURATION ||
        attr_id == VIMAR_ATTR_TIMER_3_DURATION ||
        attr_id == VIMAR_ATTR_TIMER_4_DURATION ||
        attr_id == VIMAR_ATTR_AUTO_OFF_DURATION) {
        return value[0] | ((uint32_t)value[1] << 8) |
            ((uint32_t)value[2] << 16) | ((uint32_t)value[3] << 24);
    }
    if (attr_id == VIMAR_ATTR_DOUBLE_CLICK_WINDOW ||
        attr_id == VIMAR_ATTR_LONG_PRESS_THRESHOLD ||
        attr_id == VIMAR_ATTR_LEVEL_STEP_PERIOD ||
        attr_id == VIMAR_ATTR_RESTORE_TIMEOUT) {
        return value[0] | ((uint16_t)value[1] << 8);
    }
    return value[0];
}

static zb_ret_t custom_check_value(zb_uint16_t attr_id, zb_uint8_t endpoint,
    zb_uint8_t *value)
{
    ARG_UNUSED(endpoint);
    struct dimmer_config candidate = controller.model.config;
    return zigbee_custom_write_config(&candidate, attr_id,
        custom_value(attr_id, value)) &&
        dimmer_model_modes_supported(&candidate, platform_io_capabilities()) ?
        RET_OK : RET_OUT_OF_RANGE;
}

static void custom_write_hook(zb_uint8_t endpoint, zb_uint16_t attr_id,
    zb_uint8_t *value, zb_uint16_t manufacturer_code)
{
    ARG_UNUSED(endpoint);
    ARG_UNUSED(manufacturer_code);
    struct dimmer_config candidate = controller.model.config;
    if (zigbee_custom_write_config(&candidate, attr_id,
        custom_value(attr_id, value)) &&
        dimmer_model_modes_supported(&candidate, platform_io_capabilities())) {
        zigbee_device_cancel_gestures();
        controller.model.config = candidate;
        controller.gestures.config = candidate;
        controller.leds.config = candidate;
        app_settings_schedule_config(&candidate, k_uptime_get());
    }
}

static void recovery_after_ack(zb_uint8_t unused)
{
    ARG_UNUSED(unused);
    (void)vimar_boot_trace_request(BOOT_REASON_ZIGBEE);
    int error=platform_io_request_recovery();
    if(error)LOG_ERR("Remote recovery failed:%d",error);
}

static int phase_cut_check(void *unused, enum dimmer_phase_cut_mode mode)
{
    ARG_UNUSED(unused);
    return platform_io_check_phase_cut(mode);
}

static int phase_cut_persist(void *candidate, enum dimmer_phase_cut_mode mode)
{
    ARG_UNUSED(mode);
    return app_settings_flush_current(candidate, false, controller.model.state.level);
}

static int phase_cut_apply(void *unused, enum dimmer_phase_cut_mode mode)
{
    ARG_UNUSED(unused);
    return platform_io_set_phase_cut(mode);
}

static int configure_phase_cut(uint8_t mode)
{
    struct dimmer_config candidate = controller.model.config;
    if (!zigbee_custom_write_config(&candidate, VIMAR_ATTR_PHASE_CUT_MODE, mode))
        return -EINVAL;
    const struct phase_cut_state state = {
        .on = controller.model.state.on,
        .target_on = controller.model.state.target_on,
        .applied_on = controller.output_on,
        .transitioning = controller.output_pending,
    };
    const struct phase_cut_io io = { &candidate,
        phase_cut_check, phase_cut_persist, phase_cut_apply };
    bool saved;
    int error = phase_cut_change(controller.model.config.phase_cut_mode,
        candidate.phase_cut_mode, &state, &io, &saved);
    if (saved) {
        /* Durable settings remain authoritative even if applying the GPIO fails. */
        controller.model.config = candidate;
        controller.gestures.config = candidate;
        controller.leds.config = candidate;
        context.phase_cut_mode = (uint8_t)candidate.phase_cut_mode;
        zigbee_device_cancel_gestures();
        if (error) application_controller_output_failed(&controller,
            controller.model.state.operation_id, DIMMER_FAULT_SECONDARY_UNAVAILABLE);
    }
    return error;
}

static zb_bool_t custom_command_handler(zb_uint8_t buffer)
{
    if (buffer == ZB_ZCL_GENERAL_GET_CMD_LISTS_PARAM) {
        ZCL_CTX().zb_zcl_cluster_cmd_list = &custom_server_commands;
        return ZB_TRUE;
    }
    zb_zcl_parsed_hdr_t header;
    ZB_ZCL_COPY_PARSED_HEADER(buffer, &header);
    zb_uint8_t *payload = zb_buf_begin(buffer);
    zb_ret_t result = RET_OK;

    if (header.cmd_id == VIMAR_COMMAND_CLEAR_LED_OVERRIDE && zb_buf_len(buffer) == 0) {
        led_controller_clear_override(&controller.leds);
    } else if (header.cmd_id == VIMAR_COMMAND_APPLY_LED_OVERRIDE &&
               zb_buf_len(buffer) == ZIGBEE_CUSTOM_LED_OVERRIDE_SIZE) {
        struct zigbee_custom_led_override value;
        if (!zigbee_custom_decode_led_override(payload, zb_buf_len(buffer), &value)) {
            result = RET_INVALID_PARAMETER;
        } else {
            struct led_output output = { value.r, value.g, value.b,
                value.intensity, (enum led_effect)value.effect };
            led_controller_set_override(&controller.leds, &output,
                k_uptime_get(), value.duration_ms);
        }
    } else if (header.cmd_id == VIMAR_COMMAND_REQUEST_SNAPSHOT &&
               zb_buf_len(buffer) == 0) {
        request_snapshot();
    } else if (header.cmd_id == VIMAR_COMMAND_BYPASS_ON &&
               zb_buf_len(buffer) == 0) {
        zigbee_device_cancel_gestures();
        application_controller_bypass_on(&controller, k_uptime_get());
    } else if(header.cmd_id==VIMAR_COMMAND_SET_OUTPUT) {
        bool on;uint8_t level;
        if(!zigbee_custom_decode_set_output(payload,zb_buf_len(buffer),&on,&level)) {
            result=RET_INVALID_PARAMETER;
        } else {
            zigbee_device_cancel_gestures();
            application_controller_command(&controller,on,level,DIMMER_SOURCE_ZIGBEE,k_uptime_get());
        }
    } else if(header.cmd_id==VIMAR_COMMAND_SET_PHASE_CUT) {
        if (zb_buf_len(buffer) != 1 || payload[0] >= DIMMER_PHASE_MODE_COUNT) {
            result = RET_INVALID_PARAMETER;
        } else {
            int error = configure_phase_cut(payload[0]);
            result = error == 0 ? RET_OK : RET_ERROR;
        }
    } else if(header.cmd_id==VIMAR_COMMAND_ENTER_RECOVERY && zb_buf_len(buffer)==0) {
        result=IS_ENABLED(CONFIG_VIMAR_HARDWARE) ?
            ZB_SCHEDULE_APP_ALARM(recovery_after_ack,0,ZB_MILLISECONDS_TO_BEACON_INTERVAL(750)) : RET_NOT_IMPLEMENTED;
    } else {
        return ZB_FALSE;
    }
    zb_zcl_send_default_handler(buffer, &header,
        zb_zcl_map_ret_code_to_zcl_status(result));
    return ZB_TRUE;
}

void vimar_custom_cluster_init_server(void)
{
    (void)zb_zcl_add_cluster_handlers(VIMAR_CUSTOM_CLUSTER_ID,
        ZB_ZCL_CLUSTER_SERVER_ROLE, custom_check_value, custom_write_hook,
        custom_command_handler);
}

ZB_ZCL_DECLARE_IDENTIFY_ATTRIB_LIST(identify_attrs, &context.identify.identify_time);
ZB_ZCL_DECLARE_GROUPS_ATTRIB_LIST(groups_attrs, &context.groups.name_support);
ZB_ZCL_DECLARE_SCENES_ATTRIB_LIST(scenes_attrs, &context.scenes.scene_count,
    &context.scenes.current_scene, &context.scenes.current_group,
    &context.scenes.scene_valid, &context.scenes.name_support);
ZB_ZCL_DECLARE_BASIC_ATTRIB_LIST_EXT(basic_attrs, &context.basic.zcl_version,
    &context.basic.app_version, &context.basic.stack_version,
    &context.basic.hw_version, context.basic.mf_name, context.basic.model_id,
    context.basic.date_code, &context.basic.power_source,
    context.basic.location_id, &context.basic.ph_env, context.basic.sw_ver);
ZB_ZCL_DECLARE_ON_OFF_ATTRIB_LIST(on_off_attrs, &context.on_off.on_off);
ZB_ZCL_DECLARE_LEVEL_CONTROL_ATTRIB_LIST(level_attrs, &context.level.current_level,
    &context.level.remaining_time);
ZB_DECLARE_VIMAR_CUSTOM_ATTR_LIST(custom_attrs, &context);

ZB_DECLARE_DIMMABLE_LIGHT_CLUSTER_LIST(clusters, basic_attrs, identify_attrs,
    groups_attrs, scenes_attrs, on_off_attrs, level_attrs, custom_attrs);
ZB_DECLARE_DIMMABLE_LIGHT_EP(endpoint, VIMAR_ZIGBEE_ENDPOINT, clusters);
ZBOSS_DECLARE_DEVICE_CTX_1_EP(device_context, endpoint);

static void start_snapshot(void);
static void publish_model(void);
static void refresh_timer_diagnostics(uint64_t now_ms, bool force);

static void schedule_snapshot_action(struct zigbee_report_action action);

#if defined(CONFIG_VIMAR_FAULT_DIAGNOSTICS)
static bool fault_status_announced;
static void fault_status_sent(zb_bufid_t buffer)
{
    zb_zcl_command_send_status_t *status=ZB_BUF_GET_PARAM(buffer,zb_zcl_command_send_status_t);
    if(status->status!=RET_OK)fault_status_announced=false;
    zb_buf_free(buffer);
}
static void send_fault_status(zb_bufid_t buffer)
{
    zb_uint16_t coordinator=ZB_NWK_COORDINATOR_ADDR;
    zb_uint8_t *command=ZB_ZCL_START_PACKET(buffer);
    ZB_ZCL_CONSTRUCT_GENERAL_COMMAND_REQ_FRAME_CONTROL_A(command,ZB_ZCL_FRAME_DIRECTION_TO_CLI,ZB_ZCL_NOT_MANUFACTURER_SPECIFIC,ZB_ZCL_DISABLE_DEFAULT_RESPONSE);
    ZB_ZCL_CONSTRUCT_COMMAND_HEADER(command,ZB_ZCL_GET_SEQ_NUM(),ZB_ZCL_CMD_REPORT_ATTRIB);
    ZB_ZCL_PACKET_PUT_DATA16_VAL(command,VIMAR_ATTR_FAULT_DIAG_STATUS);
    ZB_ZCL_PACKET_PUT_DATA8(command,ZB_ZCL_ATTR_TYPE_U32);
    ZB_ZCL_PACKET_PUT_DATA32_VAL(command,context.fault_diag_status);
    zb_ret_t rc=zb_zcl_finish_and_send_packet(buffer,command,(const zb_addr_u *)(const void *)&coordinator,
        ZB_APS_ADDR_MODE_16_ENDP_PRESENT,VIMAR_ZIGBEE_ENDPOINT,VIMAR_ZIGBEE_ENDPOINT,ZB_AF_HA_PROFILE_ID,VIMAR_CUSTOM_CLUSTER_ID,fault_status_sent);
    if(rc!=RET_OK){fault_status_announced=false;zb_buf_free(buffer);}
}
#endif

static void snapshot_complete(bool success)
{
#if defined(CONFIG_VIMAR_FAULT_DIAGNOSTICS)
    /* Announce saved evidence once per boot, in a separate10-byte ZCL report.
     * The full record is fetched one32-byte chunk per read; no large report. */
    if(success && (context.fault_diag_status&2u) && !fault_status_announced) {
        fault_status_announced=true;
        if(zb_buf_get_out_delayed(send_fault_status)!=RET_OK)fault_status_announced=false;
    }
#endif
    schedule_snapshot_action(
        zigbee_report_policy_complete(&report_policy, success));
}

static void retry_snapshot(zb_uint8_t unused)
{
    ARG_UNUSED(unused);
    start_snapshot();
}

static void schedule_snapshot_action(struct zigbee_report_action action)
{
    zb_ret_t error;

    if (action.kind == ZIGBEE_REPORT_SEND_NOW) {
        start_snapshot();
    } else if (action.kind == ZIGBEE_REPORT_SEND_AFTER) {
        error = ZB_SCHEDULE_APP_ALARM(retry_snapshot, 0,
            ZB_MILLISECONDS_TO_BEACON_INTERVAL(action.delay_ms));
        if (error != RET_OK) {
            LOG_WRN("Could not schedule state report retry: %d", error);
            snapshot_complete(false);
        }
    }
}

static void timer_diagnostics_report_sent(zb_bufid_t buffer)
{
    timer_report_active = false;
    zb_buf_free(buffer);
}

static void send_timer_diagnostics_report(zb_bufid_t buffer)
{
    zb_uint16_t coordinator = ZB_NWK_COORDINATOR_ADDR;
    zb_uint8_t *command = ZB_ZCL_START_PACKET(buffer);

    ZB_ZCL_CONSTRUCT_GENERAL_COMMAND_REQ_FRAME_CONTROL_A(command,
        ZB_ZCL_FRAME_DIRECTION_TO_CLI, ZB_ZCL_NOT_MANUFACTURER_SPECIFIC,
        ZB_ZCL_DISABLE_DEFAULT_RESPONSE);
    ZB_ZCL_CONSTRUCT_COMMAND_HEADER(command, ZB_ZCL_GET_SEQ_NUM(),
        ZB_ZCL_CMD_REPORT_ATTRIB);
    ZB_ZCL_PACKET_PUT_DATA16_VAL(command, VIMAR_ATTR_TIMER_ACTIVE);
    ZB_ZCL_PACKET_PUT_DATA8(command, ZB_ZCL_ATTR_TYPE_BOOL);
    ZB_ZCL_PACKET_PUT_DATA8(command, context.timer_active);
    ZB_ZCL_PACKET_PUT_DATA16_VAL(command, VIMAR_ATTR_AUTO_OFF_BYPASSED);
    ZB_ZCL_PACKET_PUT_DATA8(command, ZB_ZCL_ATTR_TYPE_BOOL);
    ZB_ZCL_PACKET_PUT_DATA8(command, context.auto_off_bypassed);
    ZB_ZCL_PACKET_PUT_DATA16_VAL(command, VIMAR_ATTR_TIMER_REMAINING);
    ZB_ZCL_PACKET_PUT_DATA8(command, ZB_ZCL_ATTR_TYPE_U32);
    ZB_ZCL_PACKET_PUT_DATA32_VAL(command, context.timer_remaining_s);
    zb_ret_t error = zb_zcl_finish_and_send_packet(buffer, command,
        (const zb_addr_u *)(const void *)&coordinator,
        ZB_APS_ADDR_MODE_16_ENDP_PRESENT, VIMAR_ZIGBEE_ENDPOINT,
        VIMAR_ZIGBEE_ENDPOINT, ZB_AF_HA_PROFILE_ID,
        VIMAR_CUSTOM_CLUSTER_ID, timer_diagnostics_report_sent);
    if (error != RET_OK) {
        timer_report_active = false;
        zb_buf_free(buffer);
    }
}

static void refresh_timer_diagnostics(uint64_t now_ms, bool force)
{
    const struct dimmer_state *state = application_controller_state(&controller);
    zb_bool_t active = state->off_timer_active;
    zb_bool_t bypassed = state->auto_off_bypassed;
    uint32_t remaining = dimmer_model_timer_remaining_s(&controller.model, now_ms);
    bool changed = active != context.timer_active ||
        bypassed != context.auto_off_bypassed ||
        (!active && context.timer_remaining_s != 0);
    bool cadence = active && remaining != context.timer_remaining_s &&
        (remaining <= 10U || now_ms - last_timer_report_ms >= 10000U);

    context.timer_active = active;
    context.auto_off_bypassed = bypassed;
    context.timer_remaining_s = remaining;
    if (ZB_JOINED() && !timer_report_active && (force || changed || cadence)) {
        if (zb_buf_get_out_delayed(send_timer_diagnostics_report) == RET_OK) {
            timer_report_active = true;
            last_timer_report_ms = now_ms;
        }
    }
}

static void request_snapshot(void)
{
    bool joined = ZB_JOINED();
    refresh_timer_diagnostics(k_uptime_get(), true);
    LOG_DBG("Accepted-state snapshot requested; joined=%d", joined);
    if (joined) {
        struct zigbee_report_action action =
            zigbee_report_policy_request(&report_policy);
        LOG_DBG("Accepted-state snapshot action=%d", action.kind);
        schedule_snapshot_action(action);
    }
}

static void refresh_led_runtime(uint64_t now_ms)
{
    led_controller_set_identifying(&controller.leds, context.identify.identify_time != 0);
    led_controller_set_fault(&controller.leds, controller.model.state.fault.active);
    struct led_output led = led_controller_resolve(&controller.leds,
        controller.model.state.on, controller.model.state.level, now_ms);
    enum wireless_status_led_mode connection_mode=connection_pairing_mode(&connection_pairing);
    bool selector_visible=connection_selecting&&connection_mode!=WIRELESS_STATUS_LED_PAIRED;
    if(selector_visible)connection_mode=WIRELESS_STATUS_LED_SELECTOR;
    uint64_t connection_since=selector_visible?
        connection_selector_since:connection_pairing.since_ms;
    led=wireless_status_led_resolve(connection_mode,
        controller.model.state.fault.active||vimar_power_protection_blocked(),
        &led,now_ms-connection_since);
    /* Fault priority bypasses the resolver's override expiry check. */
    bool override_active = controller.leds.override.active &&
        (!controller.leds.override.expires_ms ||
         now_ms < controller.leds.override.expires_ms);
    bool changed = context.led_runtime_r != led.r ||
        context.led_runtime_g != led.g || context.led_runtime_b != led.b ||
        context.led_runtime_intensity != led.intensity ||
        context.led_runtime_effect != (uint8_t)led.effect ||
        context.led_override_active != override_active;
    context.led_runtime_r = led.r;
    context.led_runtime_g = led.g;
    context.led_runtime_b = led.b;
    context.led_runtime_intensity = led.intensity;
    context.led_runtime_effect = (uint8_t)led.effect;
    context.led_override_active = override_active;
    platform_io_led(&led, now_ms);
    led_report_pending |= changed;
    if (led_report_pending && now_ms - last_led_report_ms >= LED_RUNTIME_REPORT_INTERVAL_MS) {
        led_report_pending = false;
        last_led_report_ms = now_ms;
        request_snapshot();
    }
}

static void event_sent(zb_bufid_t buffer)
{
    zb_buf_free(buffer);
    if (event_count != 0) {
        event_head = (event_head + 1U) % ARRAY_SIZE(event_queue);
        --event_count;
    }
    event_send_active = false;
    if (event_count != 0 && zb_buf_get_out_delayed(send_next_event) == RET_OK) {
        event_send_active = true;
    }
}

static void send_next_event(zb_bufid_t buffer)
{
    zb_uint16_t coordinator = ZB_NWK_COORDINATOR_ADDR;
    uint8_t payload[ZIGBEE_CUSTOM_EVENT_SIZE];
    zb_uint8_t *command = ZB_ZCL_START_PACKET(buffer);
    size_t length = zigbee_custom_encode_event(&event_queue[event_head], payload,
                                                sizeof(payload));
    ZB_ZCL_CONSTRUCT_SPECIFIC_COMMAND_REQ_FRAME_CONTROL_A(command,
        ZB_ZCL_FRAME_DIRECTION_TO_CLI, ZB_ZCL_NOT_MANUFACTURER_SPECIFIC,
        ZB_ZCL_DISABLE_DEFAULT_RESPONSE);
    ZB_ZCL_CONSTRUCT_COMMAND_HEADER(command, ZB_ZCL_GET_SEQ_NUM(),
                                    VIMAR_COMMAND_EVENT);
    for (size_t i = 0; i < length; ++i) {
        ZB_ZCL_PACKET_PUT_DATA8(command, payload[i]);
    }
    zb_ret_t error = zb_zcl_finish_and_send_packet(buffer, command,
        (const zb_addr_u *)(const void *)&coordinator,
        ZB_APS_ADDR_MODE_16_ENDP_PRESENT, VIMAR_ZIGBEE_ENDPOINT,
        VIMAR_ZIGBEE_ENDPOINT, ZB_AF_HA_PROFILE_ID,
        VIMAR_CUSTOM_CLUSTER_ID, event_sent);
    if (error != RET_OK) {
        event_sent(buffer);
    }
}

static void queue_event(const struct zigbee_custom_event *event)
{
    if (!ZB_JOINED()) return;
    if (event_count == ARRAY_SIZE(event_queue)) {
        event_head = (event_head + 1U) % ARRAY_SIZE(event_queue);
        --event_count;
    }
    event_queue[(event_head + event_count) % ARRAY_SIZE(event_queue)] = *event;
    ++event_count;
    if (!event_send_active && zb_buf_get_out_delayed(send_next_event) == RET_OK) {
        event_send_active = true;
    }
}

static void send_protection_report(zb_bufid_t buffer);

static void led_runtime_report_sent(zb_bufid_t buffer)
{
    zb_zcl_command_send_status_t *status =
        ZB_BUF_GET_PARAM(buffer, zb_zcl_command_send_status_t);
    bool success = status->status == RET_OK;
    zb_buf_free(buffer);
    if(!success)snapshot_complete(false);
    else if(zb_buf_get_out_delayed(send_protection_report)!=RET_OK)snapshot_complete(false);
}

static void send_led_runtime_report(zb_bufid_t buffer)
{
    BUILD_ASSERT(57U <= ZB_ZCL_HI_MAX_PAYLOAD_SIZE,
        "LED/boot snapshot must fit extended-address ZCL payload");
    zb_uint16_t coordinator = ZB_NWK_COORDINATOR_ADDR;
    zb_uint8_t *command = ZB_ZCL_START_PACKET(buffer);
    ZB_ZCL_CONSTRUCT_GENERAL_COMMAND_REQ_FRAME_CONTROL_A(command,
        ZB_ZCL_FRAME_DIRECTION_TO_CLI, ZB_ZCL_NOT_MANUFACTURER_SPECIFIC,
        ZB_ZCL_DISABLE_DEFAULT_RESPONSE);
    ZB_ZCL_CONSTRUCT_COMMAND_HEADER(command, ZB_ZCL_GET_SEQ_NUM(),
        ZB_ZCL_CMD_REPORT_ATTRIB);
    ZB_ZCL_PACKET_PUT_DATA16_VAL(command, VIMAR_ATTR_LED_RUNTIME_R);
    ZB_ZCL_PACKET_PUT_DATA8(command, ZB_ZCL_ATTR_TYPE_U8);
    ZB_ZCL_PACKET_PUT_DATA8(command, context.led_runtime_r);
    ZB_ZCL_PACKET_PUT_DATA16_VAL(command, VIMAR_ATTR_LED_RUNTIME_G);
    ZB_ZCL_PACKET_PUT_DATA8(command, ZB_ZCL_ATTR_TYPE_U8);
    ZB_ZCL_PACKET_PUT_DATA8(command, context.led_runtime_g);
    ZB_ZCL_PACKET_PUT_DATA16_VAL(command, VIMAR_ATTR_LED_RUNTIME_B);
    ZB_ZCL_PACKET_PUT_DATA8(command, ZB_ZCL_ATTR_TYPE_U8);
    ZB_ZCL_PACKET_PUT_DATA8(command, context.led_runtime_b);
    ZB_ZCL_PACKET_PUT_DATA16_VAL(command, VIMAR_ATTR_LED_RUNTIME_INTENSITY);
    ZB_ZCL_PACKET_PUT_DATA8(command, ZB_ZCL_ATTR_TYPE_U8);
    ZB_ZCL_PACKET_PUT_DATA8(command, context.led_runtime_intensity);
    ZB_ZCL_PACKET_PUT_DATA16_VAL(command, VIMAR_ATTR_LED_RUNTIME_EFFECT);
    ZB_ZCL_PACKET_PUT_DATA8(command, ZB_ZCL_ATTR_TYPE_U8);
    ZB_ZCL_PACKET_PUT_DATA8(command, context.led_runtime_effect);
    ZB_ZCL_PACKET_PUT_DATA16_VAL(command, VIMAR_ATTR_LED_OVERRIDE_ACTIVE);
    ZB_ZCL_PACKET_PUT_DATA8(command, ZB_ZCL_ATTR_TYPE_BOOL);
    ZB_ZCL_PACKET_PUT_DATA8(command, context.led_override_active);
    ZB_ZCL_PACKET_PUT_DATA16_VAL(command, VIMAR_ATTR_APPLIED_OUTPUT_ON);
    ZB_ZCL_PACKET_PUT_DATA8(command, ZB_ZCL_ATTR_TYPE_BOOL);
    ZB_ZCL_PACKET_PUT_DATA8(command, context.applied_output_on);
    ZB_ZCL_PACKET_PUT_DATA16_VAL(command, VIMAR_ATTR_APPLIED_OUTPUT_LEVEL);
    ZB_ZCL_PACKET_PUT_DATA8(command, ZB_ZCL_ATTR_TYPE_U8);
    ZB_ZCL_PACKET_PUT_DATA8(command, context.applied_output_level);
    ZB_ZCL_PACKET_PUT_DATA16_VAL(command, VIMAR_ATTR_TRANSITION_ACTIVE);
    ZB_ZCL_PACKET_PUT_DATA8(command, ZB_ZCL_ATTR_TYPE_BOOL);
    ZB_ZCL_PACKET_PUT_DATA8(command, context.transition_active);
    /* Move boot fields from the protection report into the existing LED
     * frame:57+52 bytes replaces39+70, with the same packet count. */
    ZB_ZCL_PACKET_PUT_DATA16_VAL(command,VIMAR_ATTR_LAST_BOOT_REASON);
    ZB_ZCL_PACKET_PUT_DATA8(command,ZB_ZCL_ATTR_TYPE_U8);
    ZB_ZCL_PACKET_PUT_DATA8(command,context.last_boot_reason);
    ZB_ZCL_PACKET_PUT_DATA16_VAL(command,VIMAR_ATTR_LAST_RESET_FLAGS);
    ZB_ZCL_PACKET_PUT_DATA8(command,ZB_ZCL_ATTR_TYPE_U32);
    ZB_ZCL_PACKET_PUT_DATA32_VAL(command,context.last_reset_flags);
    ZB_ZCL_PACKET_PUT_DATA16_VAL(command,VIMAR_ATTR_BOOT_SEQUENCE);
    ZB_ZCL_PACKET_PUT_DATA8(command,ZB_ZCL_ATTR_TYPE_U32);
    ZB_ZCL_PACKET_PUT_DATA32_VAL(command,context.boot_sequence);
    zb_ret_t error = zb_zcl_finish_and_send_packet(buffer, command,
        (const zb_addr_u *)(const void *)&coordinator,
        ZB_APS_ADDR_MODE_16_ENDP_PRESENT, VIMAR_ZIGBEE_ENDPOINT,
        VIMAR_ZIGBEE_ENDPOINT, ZB_AF_HA_PROFILE_ID,
        VIMAR_CUSTOM_CLUSTER_ID, led_runtime_report_sent);
    if (error != RET_OK) {
        zb_buf_free(buffer);
        snapshot_complete(false);
    }
}

static void protection_report_sent(zb_bufid_t buffer)
{
 zb_zcl_command_send_status_t *status=ZB_BUF_GET_PARAM(buffer,zb_zcl_command_send_status_t);
 vimar_fault_diag_report(0x80000000u|((uint32_t)VIMAR_CUSTOM_CLUSTER_ID<<8)|ZB_ZCL_CMD_REPORT_ATTRIB,52,status->status);
 bool success=status->status==RET_OK;zb_buf_free(buffer);snapshot_complete(success);
}
static void send_protection_report(zb_bufid_t buffer)
{
 BUILD_ASSERT(52U <= ZB_ZCL_HI_MAX_PAYLOAD_SIZE,
     "Protection snapshot must fit extended-address ZCL payload");
 zb_uint16_t coordinator=ZB_NWK_COORDINATOR_ADDR;
 zb_uint8_t *command=ZB_ZCL_START_PACKET(buffer);
 ZB_ZCL_CONSTRUCT_GENERAL_COMMAND_REQ_FRAME_CONTROL_A(command,ZB_ZCL_FRAME_DIRECTION_TO_CLI,ZB_ZCL_NOT_MANUFACTURER_SPECIFIC,ZB_ZCL_DISABLE_DEFAULT_RESPONSE);
 ZB_ZCL_CONSTRUCT_COMMAND_HEADER(command,ZB_ZCL_GET_SEQ_NUM(),ZB_ZCL_CMD_REPORT_ATTRIB);
 ZB_ZCL_PACKET_PUT_DATA16_VAL(command,VIMAR_ATTR_P031_ENABLED);
 ZB_ZCL_PACKET_PUT_DATA8(command,ZB_ZCL_ATTR_TYPE_BOOL);
 ZB_ZCL_PACKET_PUT_DATA8(command,context.p031_enabled);
 ZB_ZCL_PACKET_PUT_DATA16_VAL(command,VIMAR_ATTR_P031_RAW_LEVEL);
 ZB_ZCL_PACKET_PUT_DATA8(command,ZB_ZCL_ATTR_TYPE_U8);
 ZB_ZCL_PACKET_PUT_DATA8(command,context.p031_raw_level);
 ZB_ZCL_PACKET_PUT_DATA16_VAL(command,VIMAR_ATTR_P031_SAMPLE_VALID);
 ZB_ZCL_PACKET_PUT_DATA8(command,ZB_ZCL_ATTR_TYPE_BOOL);
 ZB_ZCL_PACKET_PUT_DATA8(command,context.p031_sample_valid);
 ZB_ZCL_PACKET_PUT_DATA16_VAL(command,VIMAR_ATTR_P031_LOW_QUALIFIED);
 ZB_ZCL_PACKET_PUT_DATA8(command,ZB_ZCL_ATTR_TYPE_BOOL);
 ZB_ZCL_PACKET_PUT_DATA8(command,context.p031_low_qualified);
 ZB_ZCL_PACKET_PUT_DATA16_VAL(command,VIMAR_ATTR_P031_SIGNAL_INHIBIT);
 ZB_ZCL_PACKET_PUT_DATA8(command,ZB_ZCL_ATTR_TYPE_BOOL);
 ZB_ZCL_PACKET_PUT_DATA8(command,context.p031_signal_inhibit);
 ZB_ZCL_PACKET_PUT_DATA16_VAL(command,VIMAR_ATTR_P031_OUTPUT_BLOCKED);
 ZB_ZCL_PACKET_PUT_DATA8(command,ZB_ZCL_ATTR_TYPE_BOOL);
 ZB_ZCL_PACKET_PUT_DATA8(command,context.p031_output_blocked);
 ZB_ZCL_PACKET_PUT_DATA16_VAL(command,VIMAR_ATTR_P031_NOTIFICATION);
 ZB_ZCL_PACKET_PUT_DATA8(command,ZB_ZCL_ATTR_TYPE_BOOL);
 ZB_ZCL_PACKET_PUT_DATA8(command,context.p031_notification);
 ZB_ZCL_PACKET_PUT_DATA16_VAL(command,VIMAR_ATTR_P031_TRIP_COUNT);
 ZB_ZCL_PACKET_PUT_DATA8(command,ZB_ZCL_ATTR_TYPE_U32);
 ZB_ZCL_PACKET_PUT_DATA32_VAL(command,context.p031_trip_count);
 ZB_ZCL_PACKET_PUT_DATA16_VAL(command,VIMAR_ATTR_P031_MAX_SAMPLE_GAP);
 ZB_ZCL_PACKET_PUT_DATA8(command,ZB_ZCL_ATTR_TYPE_U32);
 ZB_ZCL_PACKET_PUT_DATA32_VAL(command,context.p031_max_sample_gap_ms);
 ZB_ZCL_PACKET_PUT_DATA16_VAL(command,VIMAR_ATTR_P031_MONITOR_UPTIME);
 ZB_ZCL_PACKET_PUT_DATA8(command,ZB_ZCL_ATTR_TYPE_U32);
 ZB_ZCL_PACKET_PUT_DATA32_VAL(command,context.p031_monitor_uptime_s);
 zb_ret_t error=zb_zcl_finish_and_send_packet(buffer,command,(const zb_addr_u *)(const void *)&coordinator,
 ZB_APS_ADDR_MODE_16_ENDP_PRESENT,VIMAR_ZIGBEE_ENDPOINT,VIMAR_ZIGBEE_ENDPOINT,ZB_AF_HA_PROFILE_ID,VIMAR_CUSTOM_CLUSTER_ID,protection_report_sent);
 if(error!=RET_OK){zb_buf_free(buffer);snapshot_complete(false);}
}

static void level_report_sent(zb_bufid_t buffer)
{
    zb_zcl_command_send_status_t *status =
        ZB_BUF_GET_PARAM(buffer, zb_zcl_command_send_status_t);
    bool success = status->status == RET_OK;
    LOG_DBG("Level state report callback status=%d", status->status);

    if (!success) {
        LOG_WRN("Level state report send failed: %d", status->status);
    }
    zb_buf_free(buffer);
    if (!success) {
        snapshot_complete(false);
    } else if (zb_buf_get_out_delayed(send_led_runtime_report) != RET_OK) {
        snapshot_complete(false);
    }
}

static void send_level_report(zb_bufid_t buffer)
{
    zb_uint16_t coordinator = ZB_NWK_COORDINATOR_ADDR;
    zb_uint8_t *command = ZB_ZCL_START_PACKET(buffer);

    ZB_ZCL_CONSTRUCT_GENERAL_COMMAND_REQ_FRAME_CONTROL_A(command,
        ZB_ZCL_FRAME_DIRECTION_TO_CLI, ZB_ZCL_NOT_MANUFACTURER_SPECIFIC,
        ZB_ZCL_DISABLE_DEFAULT_RESPONSE);
    ZB_ZCL_CONSTRUCT_COMMAND_HEADER(command, ZB_ZCL_GET_SEQ_NUM(),
        ZB_ZCL_CMD_REPORT_ATTRIB);
    ZB_ZCL_PACKET_PUT_DATA16_VAL(command,
        ZB_ZCL_ATTR_LEVEL_CONTROL_CURRENT_LEVEL_ID);
    ZB_ZCL_PACKET_PUT_DATA8(command, ZB_ZCL_ATTR_TYPE_U8);
    ZB_ZCL_PACKET_PUT_DATA8(command, context.level.current_level);
    zb_ret_t error = zb_zcl_finish_and_send_packet(buffer, command,
        (const zb_addr_u *)(const void *)&coordinator,
        ZB_APS_ADDR_MODE_16_ENDP_PRESENT, VIMAR_ZIGBEE_ENDPOINT,
        VIMAR_ZIGBEE_ENDPOINT, ZB_AF_HA_PROFILE_ID,
        ZB_ZCL_CLUSTER_ID_LEVEL_CONTROL, level_report_sent);
    if (error != RET_OK) {
        LOG_WRN("Level state report was rejected immediately: %d", error);
        zb_buf_free(buffer);
        snapshot_complete(false);
    }
}

static void on_off_report_sent(zb_bufid_t buffer)
{
    zb_zcl_command_send_status_t *status =
        ZB_BUF_GET_PARAM(buffer, zb_zcl_command_send_status_t);
    bool success = status->status == RET_OK;
    LOG_DBG("On/off state report callback status=%d", status->status);

    if (!success) {
        LOG_WRN("On/off state report send failed: %d", status->status);
    }
    zb_buf_free(buffer);
    if (!success) {
        snapshot_complete(false);
        return;
    }

    zb_ret_t error = zb_buf_get_out_delayed(send_level_report);
    if (error != RET_OK) {
        LOG_WRN("Could not allocate level state report buffer: %d", error);
        snapshot_complete(false);
    }
}

static void send_on_off_report(zb_bufid_t buffer)
{
    zb_uint16_t coordinator = ZB_NWK_COORDINATOR_ADDR;
    zb_uint8_t *command = ZB_ZCL_START_PACKET(buffer);

    ZB_ZCL_CONSTRUCT_GENERAL_COMMAND_REQ_FRAME_CONTROL_A(command,
        ZB_ZCL_FRAME_DIRECTION_TO_CLI, ZB_ZCL_NOT_MANUFACTURER_SPECIFIC,
        ZB_ZCL_DISABLE_DEFAULT_RESPONSE);
    ZB_ZCL_CONSTRUCT_COMMAND_HEADER(command, ZB_ZCL_GET_SEQ_NUM(),
        ZB_ZCL_CMD_REPORT_ATTRIB);
    ZB_ZCL_PACKET_PUT_DATA16_VAL(command, ZB_ZCL_ATTR_ON_OFF_ON_OFF_ID);
    ZB_ZCL_PACKET_PUT_DATA8(command, ZB_ZCL_ATTR_TYPE_BOOL);
    ZB_ZCL_PACKET_PUT_DATA8(command, context.on_off.on_off);
    zb_ret_t error = zb_zcl_finish_and_send_packet(buffer, command,
        (const zb_addr_u *)(const void *)&coordinator,
        ZB_APS_ADDR_MODE_16_ENDP_PRESENT, VIMAR_ZIGBEE_ENDPOINT,
        VIMAR_ZIGBEE_ENDPOINT, ZB_AF_HA_PROFILE_ID,
        ZB_ZCL_CLUSTER_ID_ON_OFF, on_off_report_sent);
    if (error != RET_OK) {
        LOG_WRN("On/off state report was rejected immediately: %d", error);
        zb_buf_free(buffer);
        snapshot_complete(false);
    }
}

static void start_snapshot(void)
{
    zb_ret_t error = zb_buf_get_out_delayed(send_on_off_report);

    if (error != RET_OK) {
        LOG_WRN("Could not allocate state snapshot buffer: %d", error);
        snapshot_complete(false);
    }
}

static void heartbeat_snapshot(zb_uint8_t unused)
{
    ARG_UNUSED(unused);
    request_snapshot();
    zb_ret_t error = ZB_SCHEDULE_APP_ALARM(heartbeat_snapshot, 0,
        ZB_MILLISECONDS_TO_BEACON_INTERVAL(STATE_SNAPSHOT_INTERVAL_MS));
    if (error != RET_OK) {
        LOG_WRN("Could not schedule state snapshot heartbeat: %d", error);
    }
}

static void start_reconciliation(void)
{
    (void)ZB_SCHEDULE_APP_ALARM_CANCEL(heartbeat_snapshot, ZB_ALARM_ANY_PARAM);
    request_snapshot();
    zb_ret_t error = ZB_SCHEDULE_APP_ALARM(heartbeat_snapshot, 0,
        ZB_MILLISECONDS_TO_BEACON_INTERVAL(STATE_SNAPSHOT_INTERVAL_MS));
    if (error != RET_OK) {
        LOG_WRN("Could not start state snapshot heartbeat: %d", error);
    }
}

static void refresh_protection_diagnostics(void)
{
    vimar_fault_diag_export(context.fault_diag,&context.fault_diag_status);
#if defined(CONFIG_VIMAR_P031_PROTECTION)
    struct candidate_power_protection s;vimar_power_protection_snapshot(&s);
    context.p031_enabled=true;context.p031_raw_level=s.raw_high;
    context.p031_sample_valid=s.raw_valid;context.p031_low_qualified=s.low_qualified;
    context.p031_signal_inhibit=s.inhibit;context.p031_output_blocked=vimar_power_protection_blocked();
    context.p031_notification=s.notification;context.p031_trip_count=s.trips;
    context.p031_max_sample_gap_ms=s.max_gap_ms;
    uint64_t seconds=(k_uptime_get()-s.first_sample_ms)/1000U;context.p031_monitor_uptime_s=seconds>UINT32_MAX?UINT32_MAX:(uint32_t)seconds;
    struct boot_trace_entry entry;vimar_boot_trace_snapshot(&entry);
    context.last_boot_reason=entry.reason;context.last_reset_flags=entry.reset_flags;context.boot_sequence=entry.sequence;
#endif
}

static void refresh_output_diagnostics(void)
{
    bool on=controller.output_on;
    uint8_t level=on?controller.output_level:0;
    bool changed=context.applied_output_on!=on || context.applied_output_level!=level ||
        context.transition_active!=controller.output_pending;
    context.applied_output_on=on;context.applied_output_level=level;
    context.transition_active=controller.output_pending;
    output_report_pending |= changed;
    uint64_t now=k_uptime_get();
    if(output_report_pending && (!controller.output_pending || now-last_output_report_ms>=250)){
        output_report_pending=false;last_output_report_ms=now;request_snapshot();
    }
}

static void publish_model(void)
{
    uint64_t now_ms = k_uptime_get();
    const struct dimmer_state *state = application_controller_state(&controller);
    context.on_off.on_off = state->on;
    context.level.current_level = state->level;
    refresh_output_diagnostics();
    context.target_on = state->target_on;
    context.target_level = state->target_level;
    context.restore_pending = state->restore_waiting;
    context.fault_code = state->fault.active ? state->fault.code : DIMMER_FAULT_NONE;
    ZB_ZCL_SET_ATTRIBUTE(VIMAR_ZIGBEE_ENDPOINT, ZB_ZCL_CLUSTER_ID_ON_OFF,
        ZB_ZCL_CLUSTER_SERVER_ROLE, ZB_ZCL_ATTR_ON_OFF_ON_OFF_ID,
        (zb_uint8_t *)&context.on_off.on_off, ZB_FALSE);
    ZB_ZCL_SET_ATTRIBUTE(VIMAR_ZIGBEE_ENDPOINT, ZB_ZCL_CLUSTER_ID_LEVEL_CONTROL,
        ZB_ZCL_CLUSTER_SERVER_ROLE, ZB_ZCL_ATTR_LEVEL_CONTROL_CURRENT_LEVEL_ID,
        &context.level.current_level, ZB_FALSE);
    platform_io_render(state->on);
    refresh_led_runtime(now_ms);
    refresh_timer_diagnostics(now_ms, false);
    app_settings_schedule_state(state->on, state->level, now_ms);
}

void zigbee_device_cancel_attachment(void)
{
    application_controller_cancel_attachment(&controller);
    platform_io_cancel_attachment();
    application_controller_attachment_edge(&controller,false,k_uptime_get());
}
void zigbee_device_cancel_gestures(void)
{
    application_controller_cancel_gestures(&controller);
    platform_io_cancel_attachment();
    application_controller_attachment_edge(&controller,false,k_uptime_get());
}

void zigbee_device_local_edge_at(uint8_t encoded_edge,uint64_t timestamp_ms)
{
    application_controller_button_edge(&controller,
        (enum gesture_side)(encoded_edge & 1U), (encoded_edge & 2U) != 0,
        timestamp_ms);
}
void zigbee_device_local_edge(uint8_t encoded_edge)
{ zigbee_device_local_edge_at(encoded_edge,k_uptime_get()); }

void zigbee_device_attachment_edge_at(bool pressed,uint64_t timestamp_ms)
{ application_controller_attachment_edge(&controller,pressed,timestamp_ms); }
void zigbee_device_attachment_settled(bool settled)
{ application_controller_attachment_settled(&controller,settled); }

static void state_changed(void *unused)
{
    ARG_UNUSED(unused);
    publish_model();
    request_snapshot();
}

static void secondary_request(void *unused, uint32_t operation_id,
    bool on, uint8_t level)
{
    ARG_UNUSED(unused);
    int error=platform_io_apply(on,level);
    if(error==0) {
        /* Applied command estimate; hardware profile advertises no physical feedback. */
        application_controller_feedback(&controller, operation_id, on, level);
    } else {
        application_controller_output_failed(&controller,operation_id,DIMMER_FAULT_SECONDARY_REJECTED);
    }
}

static void gesture_event(void *unused, const struct gesture_event *event)
{
    ARG_UNUSED(unused);
    LOG_DBG("Gesture event type=%d side=%d sequence=%u held=%u",
        event->type, event->side, event->sequence_id, event->held_ms);
    const struct dimmer_state *state = application_controller_state(&controller);
    const struct zigbee_custom_event custom = {
        .type = (uint8_t)event->type,
        .side = (uint8_t)event->side,
        .sequence_id = event->sequence_id,
        .held_ms = event->held_ms,
        .effective_on = state->on,
        .effective_level = state->level,
        .data = 0,
    };
    queue_event(&custom);
}

static void system_event(void *unused, enum application_system_event event,
    uint16_t data)
{
    ARG_UNUSED(unused);
    const struct dimmer_state *state = application_controller_state(&controller);
    static const uint8_t types[] = {
        [APPLICATION_EVENT_TIMER_EXPIRED] = VIMAR_EVENT_TIMER_EXPIRED,
        [APPLICATION_EVENT_RESTORE_REQUEST] = VIMAR_EVENT_RESTORE_REQUEST,
        [APPLICATION_EVENT_STATE_CORRECTION] = VIMAR_EVENT_STATE_CORRECTION,
        [APPLICATION_EVENT_FAULT] = VIMAR_EVENT_FAULT,
    };
    const struct zigbee_custom_event custom = {
        .type = types[event], .side = 0, .sequence_id = state->operation_id,
        .held_ms = 0, .effective_on = state->on,
        .effective_level = state->level, .data = data,
    };
    queue_event(&custom);
}

static void process_protection(uint64_t now_ms)
{
    static uint64_t retry_at;
    if(vimar_power_protection_cancel_pending()){
        application_controller_set_protection(&controller,true,now_ms);
        /* Protection may clear before the normal30s remembered-state save.
         * Commit OFF first, otherwise a reset can replay previous ON. */
        if(now_ms>=retry_at){
            retry_at=now_ms+1000;
            if(app_settings_flush_current(&controller.model.config,false,controller.model.state.level)==0){
                vimar_power_protection_cancel_acknowledged();retry_at=0;
            }
        }
    }
    application_controller_set_protection(&controller,vimar_power_protection_blocked(),now_ms);
}

static void refresh_ota_contract(uint64_t now_ms,bool force)
{
 if(!force && now_ms-ota_contract_updated_ms<1000u)return;
 uint8_t digest[32]={0};bool ready=false;
#if defined(CONFIG_VIMAR_ZIGBEE_OTA)
 ready=zigbee_ota_recovery_snapshot(digest);
#endif
 /* Only this serialized Zigbee scheduler context updates the attribute. RAM
  * counter only; no RF report/NVS write and no inference about reset cause. */
 ota_contract_sample++;
 (void)ota_runtime_contract_encode(ota_contract_sample,context.boot_sequence,ready,digest,context.ota_contract);
 ota_contract_updated_ms=now_ms;
}

static void application_tick(zb_uint8_t unused)
{
    vimar_fault_diag_tick((uint32_t)k_uptime_get());
    ARG_UNUSED(unused);
    uint64_t now_ms = k_uptime_get();
    connection_pairing_poll(now_ms);
    process_protection(now_ms);
    refresh_protection_diagnostics();
    refresh_ota_contract(now_ms,false);
    platform_io_tick(now_ms);
    application_controller_tick_input(&controller, now_ms,platform_io_input_settled());
    refresh_output_diagnostics();
    refresh_led_runtime(now_ms);
    refresh_timer_diagnostics(now_ms, false);
    app_settings_tick(now_ms);
    if (!IS_ENABLED(CONFIG_VIMAR_HARDWARE) && !app_factory_reset_done && was_factory_reset_done()) {
        (void)app_settings_factory_reset();
        app_factory_reset_done = true;
    }
    (void)ZB_SCHEDULE_APP_ALARM(application_tick, 0,
        ZB_MILLISECONDS_TO_BEACON_INTERVAL(APPLICATION_TICK_INTERVAL_MS));
}

static void zcl_callback(zb_bufid_t buffer)
{
    zb_zcl_device_callback_param_t *param =
        ZB_BUF_GET_PARAM(buffer, zb_zcl_device_callback_param_t);
    param->status = RET_OK;

#if defined(CONFIG_VIMAR_ZIGBEE_OTA)
    if (param->device_cb_id == ZB_ZCL_OTA_UPGRADE_VALUE_CB_ID) { zigbee_ota_callback(buffer); return; }
#endif
    if (param->device_cb_id == ZB_ZCL_LEVEL_CONTROL_SET_VALUE_CB_ID) {
        uint8_t level = param->cb_param.level_control_set_value_param.new_value;
        zigbee_device_cancel_gestures();
        application_controller_command(&controller, level != 0,
            level == 0 ? 1 : level, DIMMER_SOURCE_ZIGBEE_LEVEL, k_uptime_get());
        return;
    }
    if (param->device_cb_id == ZB_ZCL_SET_ATTR_VALUE_CB_ID &&
        param->cb_param.set_attr_value_param.cluster_id == ZB_ZCL_CLUSTER_ID_ON_OFF &&
        param->cb_param.set_attr_value_param.attr_id == ZB_ZCL_ATTR_ON_OFF_ON_OFF_ID) {
        const struct dimmer_state *state = application_controller_state(&controller);
        zigbee_device_cancel_gestures();
        application_controller_command(&controller,
            param->cb_param.set_attr_value_param.values.data8 != 0,
            state->level, DIMMER_SOURCE_ZIGBEE, k_uptime_get());
        return;
    }
    param->status = RET_NOT_IMPLEMENTED;
}

void zboss_signal_handler(zb_bufid_t buffer)
{
    zb_zdo_app_signal_hdr_t *signal_header = NULL;
    zb_zdo_app_signal_type_t signal = zb_get_app_signal(buffer, &signal_header);
    zb_ret_t status = ZB_GET_APP_SIGNAL_STATUS(buffer);
    vimar_fault_diag_signal((uint32_t)signal,status,
        IS_ENABLED(CONFIG_ZIGBEE_ROLE_ROUTER)?1u:2u);

    ARG_UNUSED(signal_header);
    if (signal != ZB_COMMON_SIGNAL_CAN_SLEEP) {
        LOG_INF("Zigbee signal: %d status: %d", signal, status);
    }
    if (!IS_ENABLED(CONFIG_VIMAR_HARDWARE)) { zigbee_led_status_update(buffer, DK_LED2); }
    connection_pairing_poll(k_uptime_get());
    bool default_allowed=true;
    if(signal==ZB_BDB_SIGNAL_DEVICE_FIRST_START) {
        /* Persist consumption before the SDK can associate. A reboot after
         * success must never replay the earlier forget-network request. */
        if(status==RET_OK&&initial_connection_intent>=CONNECTION_INITIAL&&
           initial_connection_intent!=CONNECTION_ATTEMPTED&&
           connection_intent_claim()==0) {
            connection_pairing_start(&connection_pairing,k_uptime_get());
            initial_connection_intent=CONNECTION_ATTEMPTED;
            pairing_expired=false;
        } else {default_allowed=false;zigbee_network_rejoin_abort();}
    }
    if(pairing_expired&&pairing_signal_requires_window(signal))
        default_allowed=false;
    if(zb_bdb_is_factory_new()&&
       connection_pairing_mode(&connection_pairing)!=WIRELESS_STATUS_LED_PAIRING&&
       pairing_signal_requires_window(signal))default_allowed=false;
    if(default_allowed)ZB_ERROR_CHECK(zigbee_default_signal_handler(buffer));
    if(signal==ZB_BDB_SIGNAL_STEERING&&status==RET_OK&&ZB_JOINED())
        (void)connection_pairing_joined(&connection_pairing,k_uptime_get());
    if (status == RET_OK && ZB_JOINED()) {
        switch (signal) {
        case ZB_BDB_SIGNAL_DEVICE_FIRST_START:
        case ZB_BDB_SIGNAL_DEVICE_REBOOT:
        case ZB_BDB_SIGNAL_STEERING:
        case ZB_BDB_SIGNAL_TC_REJOIN_DONE:
#if defined(CONFIG_VIMAR_ZIGBEE_OTA)
            zigbee_ota_joined();
#endif
            start_reconciliation();
            break;
        default:
            break;
        }
    }
    if (buffer != 0) {
        zb_buf_free(buffer);
    }
}

int zigbee_device_prepare_recovery(void)
{
    const struct dimmer_state *state = application_controller_state(&controller);
    return app_settings_flush_current(&controller.model.config, state->on, state->level);
}

static void restore_warm_handoff(uint8_t remembered_level)
{
    bool restored_on;
    uint8_t restored_level;
    int result=platform_io_restore(&restored_on, &restored_level);
    if (result == 1) {
        /* Legacy raw OFF encodes no brightness. Keep the durable logical level. */
        application_controller_restore_handoff(&controller, restored_on,
            restored_on ? restored_level : remembered_level);
    }
#if defined(CONFIG_VIMAR_P031_PROTECTION)
    else if(result<0)application_controller_restore_handoff(&controller,false,remembered_level);
#endif
}

int zigbee_device_start(void)
{
#if defined(CONFIG_VIMAR_FAULT_DIAGNOSTICS)
    /* After POST_KERNEL ZB_INIT and RAM journal readiness, before application
     * SDK setup. False error-callback returns preserve ordinary assert/reset. */
    vimar_fault_diag_sdk_register();
    extern void zb_zdo_register_assert_indication_cb(void (*cb)(zb_uint16_t,zb_int_t));
    zb_zdo_register_assert_indication_cb(vimar_diag_zboss_assert);
#endif
    struct dimmer_config config = IS_ENABLED(CONFIG_VIMAR_HARDWARE) ?
        dimmer_config_vimar_defaults() : dimmer_config_defaults();
    bool initial_on = false;
    uint8_t initial_level = 254;
    const struct application_callbacks callbacks = {
        .secondary_request = secondary_request,
        .state_changed = state_changed,
        .gesture_event = gesture_event,
        .system_event = system_event,
    };
    zigbee_report_policy_init(&report_policy);
    config.short_press_mode = DIMMER_SHORT_SYMMETRIC_TOGGLE;
    (void)app_settings_loaded(&config, &initial_on, &initial_level);
    uint8_t remembered_level = initial_level;
    if (IS_ENABLED(CONFIG_VIMAR_HARDWARE) && config.power_on_behavior==DIMMER_POWER_ON_LOCAL) {
        if (config.power_on_fallback==DIMMER_POWER_FALLBACK_OFF) { initial_on=false; }
        else if(config.power_on_fallback==DIMMER_POWER_FALLBACK_ON) { initial_on=true;initial_level=config.power_on_level; }
    }
    bool unsupported=dimmer_model_sanitize_modes(&config,platform_io_capabilities());
    if(unsupported){
        LOG_WRN("Persisted modes unsupported by adapter; use dimmable/optimistic");
    }
    application_controller_init(&controller, &config, initial_on, initial_level,
        &callbacks, NULL, k_uptime_get());
    restore_warm_handoff(remembered_level);
    if(vimar_power_protection_blocked()){
        /* Before ZBOSS registration: update state without scheduling callbacks. */
        struct application_callbacks saved=controller.callbacks;
        controller.callbacks=(struct application_callbacks){0};
        application_controller_set_protection(&controller,true,k_uptime_get());
        controller.callbacks=saved;
    }
    int error = platform_io_set_phase_cut(config.phase_cut_mode);
    if (error == 0) error = platform_io_init(controller.model.state.on,controller.model.state.level);
    if (error != 0) {
        LOG_ERR("Platform I/O initialization failed: %d",error);
        if (platform_io_startup_inhibited()) {
            /* Proven gate inhibition, not an assumption about generic I/O errors.
             * Startup reconciliation must not schedule ZBOSS callbacks. */
            application_controller_restore_handoff(&controller,false,controller.model.state.level);
        }
        controller.model.state.fault=(struct dimmer_fault){.code=DIMMER_FAULT_SECONDARY_UNAVAILABLE,.active=true};
        /* Keep Zigbee and periodic button recovery running even if output init failed. */
    }

    if(unsupported){controller.model.state.fault=(struct dimmer_fault){.code=DIMMER_FAULT_UNSUPPORTED_MODE,.active=true};}
    app_settings_seed(&config,controller.model.state.on,controller.model.state.level);
    context.basic.zcl_version = ZB_ZCL_VERSION;
    context.basic.app_version = 1;
    context.basic.stack_version = 1;
    context.basic.hw_version = 1;
    ZB_ZCL_SET_STRING_VAL(context.basic.mf_name, VIMAR_MANUFACTURER,
        ZB_ZCL_STRING_CONST_SIZE(VIMAR_MANUFACTURER));
    ZB_ZCL_SET_STRING_VAL(context.basic.model_id, VIMAR_MODEL,
        ZB_ZCL_STRING_CONST_SIZE(VIMAR_MODEL));
    ZB_ZCL_SET_STRING_VAL(context.basic.sw_ver, APP_VERSION_STRING,
        ZB_ZCL_STRING_CONST_SIZE(APP_VERSION_STRING));
    context.basic.power_source = ZB_ZCL_BASIC_POWER_SOURCE_MAINS_SINGLE_PHASE;
    context.identify.identify_time = 0;
    context.level.remaining_time = 0;
    context.schema_version = VIMAR_SCHEMA_VERSION;
    context.phase_cut_mode = (uint8_t)config.phase_cut_mode;
    context.capabilities = VIMAR_CUSTOM_CAPABILITIES &
        (IS_ENABLED(CONFIG_VIMAR_HARDWARE) ? ~VIMAR_CUSTOM_CAP_DK_SIMULATOR : UINT32_MAX);
    context.initial_on_delay_ms=config.initial_on_delay_ms;
    context.rise_transition_ms=config.rise_transition_ms;
    context.fall_transition_ms=config.fall_transition_ms;
    context.min_level=config.min_level;context.max_level=config.max_level;
    context.double_click_window_ms = config.double_click_window_ms;
    context.long_press_ms = config.long_press_ms;
    context.level_step_period_ms = config.level_step_period_ms;
    context.level_step = config.level_step;
    context.short_mode = config.short_press_mode;
    context.single_up_action = config.single_up_action;
    context.single_down_action = config.single_down_action;
    context.double_up_action = config.double_up_action;
    context.double_down_action = config.double_down_action;
    context.timer_duration_s = config.timer_duration_s;
    context.timer_2_duration_s = config.timer_2_duration_s;
    context.timer_3_duration_s = config.timer_3_duration_s;
    context.timer_4_duration_s = config.timer_4_duration_s;
    context.ramp_start_level = config.ramp_start_level;
    context.ramp_end_level = config.ramp_end_level;
    context.auto_off_mode = config.auto_off_mode;
    context.auto_off_duration_s = config.auto_off_duration_s;
    context.power_on_behavior = config.power_on_behavior;
    context.power_on_fallback = config.power_on_fallback;
    context.power_on_level = config.power_on_level;
    context.restore_timeout_s = config.zigbee_restore_timeout_s;
    context.output_mode = config.output_mode;
    context.reporting_mode = config.reporting_mode;
    context.fixed_level = config.fixed_level;
    context.led_on_r = config.led_on.r; context.led_on_g = config.led_on.g;
    context.led_on_b = config.led_on.b; context.led_on_intensity = config.led_on.intensity;
    context.led_off_r = config.led_off.r; context.led_off_g = config.led_off.g;
    context.led_off_b = config.led_off.b; context.led_off_intensity = config.led_off.intensity;
    context.led_on_mode = config.led_on_intensity_mode;
    context.led_on_min = config.led_on_min_intensity;
    context.led_on_max = config.led_on_max_intensity;

#if defined(CONFIG_VIMAR_ZIGBEE_OTA)
    zigbee_ota_init();
#endif
    ZB_ZCL_REGISTER_DEVICE_CB(zcl_callback);
    ZB_AF_REGISTER_DEVICE_CTX(&device_context);
    refresh_protection_diagnostics();
    refresh_ota_contract(k_uptime_get(),true);
    publish_model();
    (void)ZB_SCHEDULE_APP_ALARM(application_tick, 0,
        ZB_MILLISECONDS_TO_BEACON_INTERVAL(APPLICATION_TICK_INTERVAL_MS));
#if defined(CONFIG_VIMAR_HARDWARE)
    zb_ieee_addr_t stock_ieee;
    vimar_identity(nrf_ficr_deviceid_get(NRF_FICR,0),
                   nrf_ficr_deviceid_get(NRF_FICR,1),stock_ieee);
    zb_set_long_address(stock_ieee);
#endif
    initial_connection_intent=connection_intent_load();
    if(initial_connection_intent==CONNECTION_REQUESTED)
        zigbee_erase_persistent_storage(ZB_TRUE);
    if(initial_connection_intent<0)
        LOG_ERR("Connection intent unreadable; automatic pairing disabled: %d",initial_connection_intent);
    zigbee_enable();
    LOG_INF("Zigbee dimmable-light endpoint started");
    return 0;
}
