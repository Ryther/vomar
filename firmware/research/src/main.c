#include "research_protocol.h"
#include "research_output.h"
#include "research_status_led.h"
#include "research_buttons.h"
#include "research_handoff.h"
#include <string.h>
#include <errno.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/retained_mem.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/retention/bootmode.h>
#include <zephyr/settings/settings.h>
#include <zephyr/sys/reboot.h>
#include <zephyr/sys/byteorder.h>

LOG_MODULE_REGISTER(vimar_lab, LOG_LEVEL_INF);

/* The default backend is DK simulation; stock output is separately opt-in. */
static struct research_state state = {
    .level = -32768,
    .capabilities = (IS_ENABLED(CONFIG_RESEARCH_STOCK_OUTPUT) ? RESEARCH_CAP_STOCK_OUTPUT :
        RESEARCH_CAP_SIMULATED) |
        (IS_ENABLED(CONFIG_RESEARCH_SOFTWARE_RECOVERY) ? RESEARCH_CAP_SOFTWARE_RECOVERY : 0),
};
static uint8_t response[20];
static bool recovery_pending;
static bool output_failed;
static struct research_buttons buttons;
static struct k_mutex state_mutex;
static struct k_work advertising_work;
static struct k_work_delayable recovery_work;
static const struct gpio_dt_spec up = GPIO_DT_SPEC_GET(DT_ALIAS(sw0), gpios);
static const struct gpio_dt_spec down = GPIO_DT_SPEC_GET(DT_ALIAS(sw1), gpios);

#define LAB_UUID BT_UUID_128_ENCODE(0xfde30805, 0xc001, 0x4a40, 0x8d00, 0x308050000001)
#define COMMAND_UUID BT_UUID_128_ENCODE(0xfde30805, 0xc001, 0x4a40, 0x8d00, 0x308050000002)
static struct bt_uuid_128 service_uuid = BT_UUID_INIT_128(LAB_UUID);
static struct bt_uuid_128 command_uuid = BT_UUID_INIT_128(COMMAND_UUID);

/* GPREGRET1 is MCUboot's boot-mode byte. GPREGRET2 is reserved here for
 * authorizing a one-shot warm recovery handoff; it is not a flash/UICR write. */
static const struct device *handoff_marker = DEVICE_DT_GET(DT_NODELABEL(gpregret2));
static bool handoff_ready;
static int handoff_load(void *context, uint8_t *data, size_t size)
{
    ARG_UNUSED(context);
    ssize_t read = settings_load_one("vimar/handoff", data, size);
    return read == (ssize_t)size ? 0 : (read < 0 ? (int)read : -EINVAL);
}
static int handoff_save(void *context, const uint8_t *data, size_t size)
{
    ARG_UNUSED(context);
    return settings_save_one("vimar/handoff", data, size);
}
static int handoff_get_marker(void *context, uint8_t *value)
{
    ARG_UNUSED(context);
    return retained_mem_read(handoff_marker, 0, value, 1);
}
static int handoff_set_marker(void *context, uint8_t value)
{
    ARG_UNUSED(context);
    return retained_mem_write(handoff_marker, 0, &value, 1);
}
static const struct research_handoff_io handoff_io = {
    .load = handoff_load, .save = handoff_save,
    .get_marker = handoff_get_marker, .set_marker = handoff_set_marker,
};

static void recover(struct k_work *work)
{
    ARG_UNUSED(work);
    k_mutex_lock(&state_mutex, K_FOREVER);
    recovery_pending = true;
    int error = handoff_ready ? research_handoff_prepare(&handoff_io, state.level) : -ENODEV;
    if (error == 0) { error = bootmode_set(BOOT_MODE_TYPE_BOOTLOADER); }
    if (error != 0) {
        if (device_is_ready(handoff_marker)) { (void)handoff_set_marker(NULL, 0); }
        LOG_ERR("Cannot request loader: %d", error);
        recovery_pending = false;
        k_mutex_unlock(&state_mutex);
        return;
    }
    /* The retained power controller has been observed holding ON/OFF/level
     * during nRF recovery. Do not send an OFF transient before reboot. */
    k_mutex_unlock(&state_mutex);
    LOG_INF("Requesting independent BLE recovery with level handoff");
    sys_reboot(SYS_REBOOT_COLD);
}

/* Caller owns state_mutex: BLE and physical keys share one output/fault path. */
static int apply_level_locked(int32_t level)
{
    int result = output_failed ? -EIO : research_output_level(level);
    if (result != 0) {
        output_failed = true;
        state.capabilities |= RESEARCH_OUTPUT_FAULT;
        state.level = RESEARCH_LEVEL_OFF;
    } else {
        state.level = level;
    }
    return result;
}

static ssize_t read_response(struct bt_conn *connection, const struct bt_gatt_attr *attribute,
                             void *buffer, uint16_t length, uint16_t offset)
{
    uint8_t snapshot[20];
    k_mutex_lock(&state_mutex, K_FOREVER);
    memcpy(snapshot, response, sizeof(snapshot));
    k_mutex_unlock(&state_mutex);
    return bt_gatt_attr_read(connection, attribute, buffer, length, offset,
                             snapshot, sizeof(snapshot));
}

static ssize_t write_request(struct bt_conn *connection, const struct bt_gatt_attr *attribute,
                             const void *buffer, uint16_t length, uint16_t offset, uint8_t flags)
{
    ARG_UNUSED(connection);
    ARG_UNUSED(attribute);
    if (offset != 0 || flags != 0) { return BT_GATT_ERR(BT_ATT_ERR_NOT_SUPPORTED); }
    if (length != 8) { return BT_GATT_ERR(BT_ATT_ERR_INVALID_ATTRIBUTE_LEN); }
    k_mutex_lock(&state_mutex, K_FOREVER);
    const uint8_t *request = buffer;
    if (recovery_pending && request[1] != RESEARCH_STATUS) {
        k_mutex_unlock(&state_mutex);
        return BT_GATT_ERR(BT_ATT_ERR_WRITE_NOT_PERMITTED);
    }
    int result = research_process(&state, buffer, length, k_uptime_get_32(), response);
    if (result == 0 && request[1] == RESEARCH_LEVEL) {
        research_buttons_cancel(&buttons); /* BLE overrides an in-flight local gesture. */
        result = apply_level_locked(state.level);
        if (result != 0) {
            sys_put_le32((uint32_t)result, response + 4);
            sys_put_le32((uint32_t)state.level, response + 8);
            sys_put_le32(state.capabilities, response + 16);
        }
    }
    bool request_recovery = state.recovery_requested;
    if (request_recovery) { recovery_pending = true; }
    state.recovery_requested = false;
    int32_t level = state.level;
    k_mutex_unlock(&state_mutex);
    LOG_INF("Diagnostic result=%d requested_level=%d compare=%u",
            result, level, research_pwm_compare(level));
    if (request_recovery) { k_work_reschedule(&recovery_work, K_MSEC(750)); }
    return length;
}

BT_GATT_SERVICE_DEFINE(lab_service,
    BT_GATT_PRIMARY_SERVICE(&service_uuid),
    BT_GATT_CHARACTERISTIC(&command_uuid.uuid, BT_GATT_CHRC_READ | BT_GATT_CHRC_WRITE,
        BT_GATT_PERM_READ_AUTHEN | BT_GATT_PERM_WRITE_AUTHEN,
        read_response, write_request, NULL));

static const struct bt_data advertising_data[] = {
    BT_DATA_BYTES(BT_DATA_FLAGS, BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR),
    BT_DATA_BYTES(BT_DATA_UUID128_ALL, LAB_UUID),
};
static const struct bt_data scan_response[] = {
    BT_DATA(BT_DATA_NAME_COMPLETE, CONFIG_BT_DEVICE_NAME, sizeof(CONFIG_BT_DEVICE_NAME) - 1),
};

static void advertise(struct k_work *work)
{
    ARG_UNUSED(work);
    int error = bt_le_adv_start(BT_LE_ADV_CONN_FAST_1, advertising_data,
                                ARRAY_SIZE(advertising_data), scan_response,
                                ARRAY_SIZE(scan_response));
    if (error != 0) { LOG_ERR("Advertising: %d", error); }
}

static void recycled(void) { k_work_submit(&advertising_work); }
static void connected(struct bt_conn *connection, uint8_t error)
{
    if (error != 0) { k_work_submit(&advertising_work); }
    else {
        int result = bt_conn_set_security(connection, BT_SECURITY_L3);
        if (result != 0) { LOG_WRN("Link security request: %d", result); }
    }
}
static void disconnected(struct bt_conn *connection, uint8_t reason)
{
    ARG_UNUSED(connection);
    ARG_UNUSED(reason);
    research_status_led_authenticated(false);
}
static void security_changed(struct bt_conn *connection, bt_security_t level,
                             enum bt_security_err error)
{
    ARG_UNUSED(connection);
    research_status_led_authenticated(error == BT_SECURITY_ERR_SUCCESS && level >= BT_SECURITY_L3);
}
BT_CONN_CB_DEFINE(callbacks) = { .connected = connected, .recycled = recycled,
    .disconnected = disconnected, .security_changed = security_changed };

int main(void)
{
    k_mutex_init(&state_mutex);
    research_buttons_init(&buttons);
    int led_error = research_status_led_init();
    if (led_error != 0) { LOG_WRN("Temporary LED init: %d", led_error); }
    int storage_error = settings_subsys_init();
    handoff_ready = storage_error == 0 && device_is_ready(handoff_marker);
    int32_t initial_level = RESEARCH_LEVEL_OFF;
    if (handoff_ready) {
        int restored = research_handoff_take(&handoff_io, &initial_level);
        if (restored < 0) { LOG_WRN("Invalid/unavailable level handoff: %d; start OFF", restored); }
    } else {
        LOG_WRN("Level handoff unavailable: settings=%d", storage_error);
        if (device_is_ready(handoff_marker)) { (void)handoff_set_marker(NULL, 0); }
    }
    state.level = initial_level;
    int output_error = research_output_init_at_level(initial_level);
    output_failed = output_error != 0;
    if (output_failed) { state.capabilities |= RESEARCH_OUTPUT_FAULT; state.level = RESEARCH_LEVEL_OFF; }
    if (output_failed) { LOG_ERR("Output init failed: %d; level writes disabled", output_error); }
    k_work_init_delayable(&recovery_work, recover);
    k_work_init(&advertising_work, advertise);
    uint8_t initial[8] = {1, RESEARCH_STATUS};
    (void)research_process(&state, initial, sizeof(initial), 0, response);
    bool buttons_ready = gpio_is_ready_dt(&up) && gpio_is_ready_dt(&down);
    if (buttons_ready) {
        buttons_ready = gpio_pin_configure_dt(&up, GPIO_INPUT) == 0 &&
                        gpio_pin_configure_dt(&down, GPIO_INPUT) == 0;
    }
    int error = bt_passkey_set(824005);
    if (error == 0) { error = bt_enable(NULL); }
    if (error != 0) { LOG_ERR("BLE setup: %d", error); return 0; }
    error = settings_load();
    if (error != 0) { LOG_WRN("Settings load: %d", error); }
    k_work_submit(&advertising_work);
    LOG_INF("BLE research console: simulated=%d software_recovery=%d",
            !IS_ENABLED(CONFIG_RESEARCH_STOCK_OUTPUT), IS_ENABLED(CONFIG_RESEARCH_SOFTWARE_RECOVERY));
    while (true) {
        uint32_t now = k_uptime_get_32();
        led_error = research_status_led_tick(now);
        if (led_error != 0) { LOG_WRN("Temporary LED stopped: %d", led_error); }
        int up_pressed = buttons_ready ? gpio_pin_get_dt(&up) : -ENODEV;
        int down_pressed = buttons_ready ? gpio_pin_get_dt(&down) : -ENODEV;
        bool request_recovery = false;
        k_mutex_lock(&state_mutex, K_FOREVER);
        if (up_pressed < 0 || down_pressed < 0) {
            research_buttons_cancel(&buttons);
            buttons.chord = false;
        } else if (!recovery_pending) {
            uint8_t mask = (up_pressed ? RESEARCH_BUTTON_UP : 0) |
                           (down_pressed ? RESEARCH_BUTTON_DOWN : 0);
            struct research_button_action action = research_buttons_tick(&buttons, now, mask, state.level);
            if (action.recovery && IS_ENABLED(CONFIG_RESEARCH_SOFTWARE_RECOVERY)) {
                recovery_pending = true;
                request_recovery = true;
            } else if (action.set_level) {
                int result = apply_level_locked(action.level);
                if (result != 0) { LOG_ERR("Button output failed: %d", result); }
            }
        }
        k_mutex_unlock(&state_mutex);
        if (request_recovery) { k_work_reschedule(&recovery_work, K_NO_WAIT); }
        k_sleep(K_MSEC(20));
    }
}
