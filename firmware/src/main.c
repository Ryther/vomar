#include <zephyr/app_version.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/settings/settings.h>

#if defined(CONFIG_BT)
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/mgmt/mcumgr/transport/smp_bt.h>
#endif

#include "zigbee_device.h"
#include "app_settings_backend.h"
#include "vimar_power_protection.h"
#include "boot_trace.h"
#include "fault_diag_zephyr.h"
#if defined(CONFIG_VIMAR_ZIGBEE_OTA)
#include "ota_storage.h"
#endif

LOG_MODULE_REGISTER(vimar_platform, LOG_LEVEL_INF);

#if defined(CONFIG_BT)
static struct k_work advertise_work;

static const struct bt_data advertising_data[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR),
	BT_DATA_BYTES(BT_DATA_UUID128_ALL, SMP_BT_SVC_UUID_VAL),
};

static const struct bt_data scan_response[] = {
	BT_DATA(BT_DATA_NAME_COMPLETE, CONFIG_BT_DEVICE_NAME,
		sizeof(CONFIG_BT_DEVICE_NAME) - 1),
};

static void advertise(struct k_work *work)
{
	ARG_UNUSED(work);
	int error = bt_le_adv_start(BT_LE_ADV_CONN_FAST_1, advertising_data,
				    ARRAY_SIZE(advertising_data), scan_response,
				    ARRAY_SIZE(scan_response));
	if (error != 0) {
		LOG_ERR("BLE advertising failed: %d", error);
	}
}

static void disconnected(struct bt_conn *connection, uint8_t reason)
{
	ARG_UNUSED(connection);
	LOG_INF("BLE disconnected: %u", reason);
}

static void connection_recycled(void)
{
	k_work_submit(&advertise_work);
	zigbee_device_start();
}

BT_CONN_CB_DEFINE(connection_callbacks) = {
	.disconnected = disconnected,
	.recycled = connection_recycled,
};

static void bluetooth_ready(int error)
{
	if (error != 0) {
		LOG_ERR("Bluetooth initialization failed: %d", error);
		return;
	}
	error = settings_load();
	if (error != 0) {
		LOG_ERR("Settings load failed: %d", error);
		return;
	}
	k_work_submit(&advertise_work);
}
#endif

int main(void)
{
	app_settings_init();
	LOG_INF("Vimar 30805 development platform %s", APP_VERSION_STRING);
    LOG_INF("Hardware adapter: %s",IS_ENABLED(CONFIG_VIMAR_HARDWARE)?"Vimar":"DK simulator");
#if defined(CONFIG_BT)
	int error = bt_passkey_set(824005);
	if (error != 0) {
		LOG_ERR("Development passkey setup failed: %d", error);
		return 0;
	}
	k_work_init(&advertise_work, advertise);
	error = bt_enable(bluetooth_ready);
	if (error != 0) {
		LOG_ERR("Bluetooth enable failed: %d", error);
	}
#else
    int error = settings_subsys_init();
    if(error==0) { error=settings_load(); }
#if defined(CONFIG_VIMAR_P031_PROTECTION)
    int protection_error=vimar_power_protection_init();
    if(protection_error)LOG_ERR("P0.31 checkpoint unavailable; output inhibited: %d",protection_error);
    (void)vimar_boot_trace_begin(BOOT_IMAGE_MAIN);
#endif
#if defined(CONFIG_VIMAR_P031_PROTECTION)
    struct boot_trace_entry diag_boot;vimar_boot_trace_snapshot(&diag_boot);
    vimar_fault_diag_boot(diag_boot.sequence);
#else
    vimar_fault_diag_boot(0);
#endif
	if (error != 0) {
#if defined(CONFIG_VIMAR_P031_PROTECTION)
        vimar_power_protection_latch_input_failure();
#endif
		LOG_ERR("Settings unavailable; stopped before output/OTA routing: %d", error);
        return 0;
	}

#if defined(CONFIG_VIMAR_ZIGBEE_OTA)
    if(ota_storage_boot_route()!=0){LOG_ERR("OTA boot routing failed; staying before output init");return 0;}
#endif
	zigbee_device_start();
#endif
	return 0;
}
