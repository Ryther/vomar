import re
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
FW = REPO / "firmware"


class PlatformSourceTests(unittest.TestCase):
    def test_sdk_revision_and_minimal_identity_are_pinned(self):
        west = (FW / "west.yml").read_text(encoding="utf-8")
        self.assertIn("url: https://github.com/nrfconnect/ncs-zigbee", west)
        self.assertIn("revision: v1.4.0", west)
        self.assertIn("revision: v3.4.0", west)
        source = (FW / "src/main.c").read_text(encoding="utf-8")
        self.assertIn("APP_VERSION_STRING", source)
        self.assertNotRegex(source, r"gpio_(pin_)?set|i2c_write|pwm_set")

    def test_mcuboot_and_ble_smp_contract(self):
        sysbuild = (FW / "sysbuild.conf").read_text(encoding="utf-8")
        self.assertIn("SB_CONFIG_BOOTLOADER_MCUBOOT=y", sysbuild)
        self.assertIn("SB_CONFIG_PARTITION_MANAGER=y", sysbuild)
        self.assertIn("SB_CONFIG_MERGED_HEX_FILES=y", sysbuild)
        config = (FW / "prj.conf").read_text(encoding="utf-8")
        for setting in (
            "CONFIG_BT=y", "CONFIG_BT_PERIPHERAL=y", "CONFIG_MCUMGR=y",
            "CONFIG_ZCBOR=y",
            "CONFIG_MCUMGR_TRANSPORT_BT=y", "CONFIG_MCUMGR_GRP_IMG=y",
            "CONFIG_MCUMGR_GRP_OS=y", "CONFIG_MCUBOOT_IMG_MANAGER=y",
            "CONFIG_IMG_MANAGER=y",
        ):
            self.assertIn(setting, config)
        self.assertIn("CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN=y", config)
        self.assertIn("CONFIG_BT_SETTINGS=y", config)
        self.assertIn("CONFIG_DISABLE_FLASH_PATCH=y", config)
        source = (FW / "src/main.c").read_text(encoding="utf-8")
        self.assertIn("settings_load()", source)
        mcuboot = (FW / "sysbuild/mcuboot.conf").read_text(encoding="utf-8")
        self.assertIn("CONFIG_REBOOT=y", mcuboot)
        self.assertIn("CONFIG_DISABLE_FLASH_PATCH=y", mcuboot)

    def test_documentation_contains_no_hardware_mutation_command(self):
        text = "\n".join(path.read_text(encoding="utf-8") for path in FW.rglob("*.*") if path.is_file())
        forbidden = ("west flash", "nrfjprog --recover", "--eraseall", "--chiperase")
        for token in forbidden:
            self.assertNotIn(token, text)

    def test_zigbee_dimmable_light_contract(self):
        config = (FW / "prj.conf").read_text(encoding="utf-8")
        self.assertIn("CONFIG_ZIGBEE_ADD_ON=y", config)
        self.assertIn("CONFIG_ZIGBEE_ROLE_ROUTER=y", config)
        source = "\n".join(
            (FW / path).read_text(encoding="utf-8")
            for path in ("src/zigbee_device.c", "src/zb_dimmable_light.h")
        )
        self.assertIn("VIMAR_ZIGBEE_ENDPOINT 1", source)
        self.assertIn('"OpenVimar"', source)
        self.assertIn('"Vimar30805-DK"', source)
        for cluster in (
            "ZB_ZCL_CLUSTER_ID_BASIC",
            "ZB_ZCL_CLUSTER_ID_IDENTIFY",
            "ZB_ZCL_CLUSTER_ID_GROUPS",
            "ZB_ZCL_CLUSTER_ID_SCENES",
            "ZB_ZCL_CLUSTER_ID_ON_OFF",
            "ZB_ZCL_CLUSTER_ID_LEVEL_CONTROL",
        ):
            self.assertIn(cluster, source)
        self.assertIn("zigbee_enable()", source)

    def test_effective_state_snapshot_reports_on_off_and_level(self):
        source = (FW / "src/zigbee_device.c").read_text(encoding="utf-8")
        self.assertIn("send_on_off_report", source)
        self.assertIn("send_level_report", source)
        self.assertIn("ZB_NWK_COORDINATOR_ADDR", source)
        self.assertIn("ZB_ZCL_CMD_REPORT_ATTRIB", source)
        self.assertIn("on_off_report_sent", source)
        self.assertIn("level_report_sent", source)
        self.assertIn("ZB_ZCL_ATTR_LEVEL_CONTROL_CURRENT_LEVEL_ID", source)
        self.assertIn("zb_buf_free(buffer)", source)

    def test_state_reconciliation_uses_policy_and_periodic_snapshot(self):
        source = (FW / "src/zigbee_device.c").read_text(encoding="utf-8")
        self.assertIn("zigbee_report_policy_request", source)
        self.assertIn("zigbee_report_policy_complete", source)
        self.assertIn("STATE_SNAPSHOT_INTERVAL_MS 60000", source)
        self.assertIn("ZB_SCHEDULE_APP_ALARM", source)
        self.assertIn("ZB_BDB_SIGNAL_DEVICE_FIRST_START", source)
        self.assertIn("ZB_BDB_SIGNAL_DEVICE_REBOOT", source)

    def test_zigbee_dk_profile_preserves_the_validated_ble_recovery_profile(self):
        base = (FW / "prj.conf").read_text(encoding="utf-8")
        zigbee = (FW / "zigbee_dk.conf").read_text(encoding="utf-8")
        self.assertIn("CONFIG_MCUMGR_TRANSPORT_BT=y", base)
        self.assertIn("CONFIG_BT=n", zigbee)
        self.assertIn("CONFIG_MCUMGR=n", zigbee)
        source = (FW / "src/main.c").read_text(encoding="utf-8")
        self.assertIn("#if defined(CONFIG_BT)", source)
        self.assertIn("zigbee_device_start();", source)

    def test_zigbee_profile_checks_durable_ota_before_output_but_keeps_dk_io_optional(self):
        main = (FW / "src/main.c").read_text(encoding="utf-8")
        zigbee = (FW / "src/zigbee_device.c").read_text(encoding="utf-8")
        non_bt = main.split("#else", 1)[1].rsplit("#endif", 1)[0]
        # Settings now include the durable OTA routing record. An unreadable
        # backend must stop before an old valid primary initializes outputs.
        self.assertIn('LOG_ERR("Settings unavailable', non_bt)
        self.assertLess(non_bt.index('ota_storage_boot_route()'),
                        non_bt.index('zigbee_device_start()'))
        self.assertNotRegex(
            zigbee,
            r"platform_io_init\(\);\s*if \(error != 0\).*?return error;",
        )
        self.assertIn('LOG_ERR("Platform I/O initialization failed', zigbee)

    def test_zigbee_dk_profile_exposes_network_diagnostics_without_uart(self):
        profile = (FW / "zigbee_dk.conf").read_text(encoding="utf-8")
        zigbee = (FW / "src/zigbee_device.c").read_text(encoding="utf-8")
        self.assertIn("CONFIG_USE_SEGGER_RTT=y", profile)
        self.assertIn("CONFIG_LOG_BACKEND_RTT=y", profile)
        self.assertIn("CONFIG_LOG_BACKEND_UART=n", profile)
        self.assertIn("CONFIG_ZIGBEE_CHANNEL_SELECTION_MODE_MULTI=y", profile)
        self.assertIn("zb_get_app_signal", zigbee)
        self.assertIn("ZB_GET_APP_SIGNAL_STATUS", zigbee)
        self.assertIn("zigbee_led_status_update(buffer, DK_LED2)", zigbee)

    def test_dk_io_is_isolated_from_the_dimmer_model(self):
        adapter = (FW / "src/platform_io_dk.c").read_text(encoding="utf-8")
        model = (FW / "src/dimmer_model.c").read_text(encoding="utf-8")
        self.assertIn("dk_buttons_init", adapter)
        self.assertIn("DK_BTN1", adapter)
        self.assertIn("DK_BTN2", adapter)
        self.assertIn("DK_BTN4_MSK", adapter)
        self.assertIn("register_factory_reset_button", adapter)
        self.assertIn("check_factory_reset_button", adapter)
        self.assertIn("dk_set_led(DK_LED1", adapter)
        self.assertIn("ZB_SCHEDULE_APP_CALLBACK", adapter)
        self.assertNotIn("DK_BTN", model)
        self.assertNotIn("DK_LED", model)

    def test_application_settings_use_an_isolated_zephyr_subtree(self):
        backend = (FW / "src/app_settings_backend.c").read_text(encoding="utf-8")
        zigbee = (FW / "src/zigbee_device.c").read_text(encoding="utf-8")
        self.assertIn('SETTINGS_STATIC_HANDLER_DEFINE(vimar_app, "vimar/app"', backend)
        self.assertIn('settings_save_one("vimar/app/state"', backend)
        self.assertIn('settings_delete("vimar/app/state")', backend)
        self.assertIn("app_settings_schedule_config", zigbee)
        self.assertIn("app_settings_tick", zigbee)

    def test_custom_writes_are_secondary_capability_gated(self):
        zigbee = (FW / "src/zigbee_device.c").read_text(encoding="utf-8")
        self.assertIn("dimmer_model_modes_supported(&candidate", zigbee)
        self.assertIn("platform_io_capabilities()", zigbee)
        for name in ("platform_io_dk.c", "platform_io_vimar.c"):
            adapter = (FW / "src" / name).read_text(encoding="utf-8")
            self.assertIn(".stock_switch_mode=false", adapter)

    def test_auto_off_controls_are_connected_to_zigbee(self):
        header = (FW / "src/zb_vimar_custom.h").read_text(encoding="utf-8")
        zigbee = (FW / "src/zigbee_device.c").read_text(encoding="utf-8")
        for attribute in (
            "VIMAR_ATTR_AUTO_OFF_MODE", "VIMAR_ATTR_AUTO_OFF_DURATION",
            "VIMAR_ATTR_AUTO_OFF_BYPASSED", "VIMAR_ATTR_TIMER_REMAINING",
        ):
            self.assertIn(attribute, header)
        self.assertIn("VIMAR_COMMAND_BYPASS_ON", zigbee)
        self.assertIn("application_controller_bypass_on", zigbee)
        self.assertIn("DIMMER_SOURCE_ZIGBEE", zigbee)
        self.assertIn("send_timer_diagnostics_report", zigbee)

    def test_hardware_acceptance_distinguishes_confirmed_and_pending_scenarios(self):
        protocol_path = REPO / "analysis/platform/dk-acceptance-protocol.md"
        if not protocol_path.is_file():
            self.skipTest("optional private hardware evidence missing: " + str(protocol_path))
        protocol = protocol_path.read_text(encoding="utf-8")
        for scenario in ("signed BLE upload", "test boot", "confirmation", "rollback", "interrupted upload", "invalid signature", "recovery"):
            self.assertIn(scenario, protocol)
        self.assertEqual(protocol.count("**CONFIRMED 2026-08-24**"), 4)
        self.assertEqual(protocol.count("**PENDING HARDWARE**"), 3)
        self.assertIn("explicit approval", protocol)


if __name__ == "__main__":
    unittest.main()
