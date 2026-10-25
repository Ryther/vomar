#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/mgmt/mcumgr/transport/smp_bt.h>
#include <zephyr/settings/settings.h>
#if defined(CONFIG_VIMAR_RECOVERY_IDENTITY)
#include "recovery_identity.h"
#endif
#if defined(CONFIG_VIMAR_RECOVERY_BOOT_HISTORY)
#include "recovery_boot_history.h"
#endif
#if defined(CONFIG_VIMAR_RECOVERY_MIGRATION_EXEC)
#include "recovery_migration.h"
#endif
#if defined(CONFIG_VIMAR_RECOVERY_BUTTON_EXIT)
#include "recovery_exit_zephyr.h"
#endif
#if defined(CONFIG_VIMAR_P031_PROTECTION)
#include "vimar_power_protection.h"
#include "boot_trace.h"
#endif
#if defined(CONFIG_VIMAR_OTA_INSTALLER)
#include "ota_install.h"
#endif

#if defined(CONFIG_VIMAR_P031_PROTECTION)
#include <zephyr/mgmt/mcumgr/mgmt/callbacks.h>
#include <zephyr/mgmt/mcumgr/mgmt/mgmt.h>
#include <zephyr/mgmt/mcumgr/grp/os_mgmt/os_mgmt_callbacks.h>
static enum mgmt_cb_return before_smp_reset(uint32_t event,enum mgmt_cb_return previous,
    int32_t *rc,uint16_t *group,bool *abort_more,void *data,size_t size)
{
 ARG_UNUSED(event);ARG_UNUSED(group);ARG_UNUSED(data);ARG_UNUSED(size);
 if(previous!=MGMT_CB_OK)return previous;
#if defined(CONFIG_VIMAR_RECOVERY_BUTTON_EXIT)
 int error=recovery_exit_zephyr_prepare_reset();
#else
 int error=vimar_power_protection_flush();
#endif
 if(error){
  *rc=MGMT_ERR_EBUSY;*abort_more=true;return MGMT_CB_ERROR_RC;
 }
 return MGMT_CB_OK;
}
static struct mgmt_callback reset_callback={.callback=before_smp_reset,.event_id=MGMT_EVT_OP_OS_MGMT_RESET};
#endif

LOG_MODULE_REGISTER(vimar_recovery, LOG_LEVEL_INF);

static struct k_work advertise_work;
static const struct bt_data advertising_data[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR),
	BT_DATA_BYTES(BT_DATA_UUID128_ALL, SMP_BT_SVC_UUID_VAL),
};
static const struct bt_data scan_response[] = {
#if defined(CONFIG_VIMAR_RECOVERY_IDENTITY)
	/* 18-byte project UUID + 12-byte shortened name fit the 31-byte response.
	 * Keep generic SMP UUID in advertising for existing exact-address clients. */
	BT_DATA_BYTES(BT_DATA_UUID128_ALL,
		BT_UUID_128_ENCODE(0x7b2f3080,0x5c91,0x4a6d,0x9f22,0x4e8c6d300805)),
	BT_DATA(BT_DATA_NAME_SHORTENED, "Vimar30805", 10),
#else
	BT_DATA(BT_DATA_NAME_COMPLETE, CONFIG_BT_DEVICE_NAME,
		sizeof(CONFIG_BT_DEVICE_NAME) - 1),
#endif
};

static void advertise(struct k_work *work)
{
	ARG_UNUSED(work);
	int error = bt_le_adv_start(BT_LE_ADV_CONN_FAST_1, advertising_data,
		ARRAY_SIZE(advertising_data), scan_response, ARRAY_SIZE(scan_response));
	if (error != 0) {
		LOG_ERR("Recovery advertising failed: %d", error);
	}
}

static void connected(struct bt_conn *connection, uint8_t error)
{
	ARG_UNUSED(connection);
	if (error != 0) {
		k_work_submit(&advertise_work);
	}
}

static void recycled(void)
{
	k_work_submit(&advertise_work);
}

static void disconnected(struct bt_conn *connection, uint8_t reason)
{
 ARG_UNUSED(connection);ARG_UNUSED(reason);
#if defined(CONFIG_VIMAR_RECOVERY_BUTTON_EXIT)
 recovery_exit_zephyr_disconnected();
#endif
}

BT_CONN_CB_DEFINE(connection_callbacks) = {
	.connected = connected,
	.disconnected = disconnected,
	.recycled = recycled,
};

int main(void)
{
#if defined(CONFIG_VIMAR_OTA_INSTALLER) || defined(CONFIG_VIMAR_P031_PROTECTION)
    int init_result=settings_subsys_init();
#endif
#if defined(CONFIG_VIMAR_P031_PROTECTION)
    if(init_result)LOG_ERR("Recovery settings init: %d",init_result);
    int protection_error=vimar_power_protection_init();
    if(init_result||protection_error)vimar_power_protection_latch_input_failure();
    if(protection_error)LOG_ERR("P0.31 checkpoint unavailable; output inhibited: %d",protection_error);
    int trace_error=vimar_boot_trace_begin(BOOT_IMAGE_RECOVERY);
    if(trace_error)LOG_ERR("Recovery entry checkpoint unavailable: %d",trace_error);
    mgmt_callback_register(&reset_callback);
#endif
#if defined(CONFIG_VIMAR_OTA_INSTALLER)
    /* Direct OTA key reads need the backend, not BT settings before bt_enable. */
    int ota_result=init_result;
    if(!init_result){ota_result=ota_install_pending();if(ota_result)LOG_ERR("OTA install stopped; BLE recovery available: %d",ota_result);}
    else LOG_ERR("OTA settings unavailable: %d",init_result);
#endif
	/* Public development credential, matching the existing DK BLE profile. */
	int error = bt_passkey_set(824005);
	if (error != 0) {
		LOG_ERR("Development passkey setup failed: %d", error);
		return 0;
	}
	error = bt_enable(NULL);
	if (error != 0) {
		LOG_ERR("Recovery Bluetooth failed: %d", error);
		return 0;
	}
	error = settings_load();
	if (error != 0) {
		/* Recovery must remain reachable even if persisted settings are bad.
		 * A client may need to forget its old bond and pair again. */
		LOG_WRN("Recovery settings load failed: %d", error);
	}
#if defined(CONFIG_VIMAR_RECOVERY_BUTTON_EXIT)
	recovery_exit_zephyr_init(init_result?init_result:error, !trace_error && !ota_result);
#endif
#if defined(CONFIG_VIMAR_RECOVERY_IDENTITY)
	recovery_identity_register();
#endif
#if defined(CONFIG_VIMAR_RECOVERY_BOOT_HISTORY)
	recovery_boot_history_register();
#endif
#if defined(CONFIG_VIMAR_RECOVERY_MIGRATION_EXEC)
	recovery_migration_register();
#endif
	k_work_init(&advertise_work, advertise);
	k_work_submit(&advertise_work);
	return 0;
}
