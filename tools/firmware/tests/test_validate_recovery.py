import copy
import importlib.util
import struct
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "validate_recovery.py"
spec = importlib.util.spec_from_file_location("validate_recovery", SCRIPT)
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class RecoveryContractTests(unittest.TestCase):
    def setUp(self):
        self.configs = {
            "mcuboot": {
                "CONFIG_BOOT_FIRMWARE_LOADER": "y",
                "CONFIG_BOOT_FIRMWARE_LOADER_ENTRANCE_GPIO": "y",
                "CONFIG_BOOT_FIRMWARE_LOADER_NO_APPLICATION": "y",
                "CONFIG_BOOT_SIGNATURE_TYPE_ECDSA_P256": "y",
                "CONFIG_BOOT_VALIDATE_SLOT0": "y",
                "CONFIG_DISABLE_FLASH_PATCH": "y",
                "CONFIG_SEGGER_RTT_INIT_MODE_ALWAYS": "y",
            },
            "firmware": {
                "CONFIG_MCUBOOT_BOOTLOADER_MODE_FIRMWARE_UPDATER": "y",
                "CONFIG_ZIGBEE_ADD_ON": "y",
                "CONFIG_DISABLE_FLASH_PATCH": "y",
                "CONFIG_SEGGER_RTT_INIT_MODE_ALWAYS": "y",
            },
            "vimar_recovery": {
                "CONFIG_MCUBOOT_BOOTLOADER_MODE_FIRMWARE_UPDATER": "y",
                "CONFIG_MCUBOOT_APPLICATION_FIRMWARE_UPDATER": "y",
                "CONFIG_MCUMGR_GRP_IMG": "y",
                "CONFIG_MCUMGR_TRANSPORT_BT": "y",
                "CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN": "y",
                "CONFIG_BT_SMP": "y",
                "CONFIG_BT_SETTINGS": "y",
                "CONFIG_MCUMGR_GRP_IMG_UPDATABLE_IMAGE_NUMBER": "1",
                "CONFIG_DISABLE_FLASH_PATCH": "y",
                "CONFIG_SEGGER_RTT_INIT_MODE_ALWAYS": "y",
            },
        }
        self.layouts = {name: dict(recovery.PARTITIONS) for name in self.configs}

    def test_valid_independent_recovery_contract(self):
        recovery.validate_contract(self.configs, self.layouts)

    def test_boot_must_validate_signature_every_time(self):
        self.configs["mcuboot"]["CONFIG_BOOT_VALIDATE_SLOT0"] = "n"
        with self.assertRaisesRegex(ValueError, "BOOT_VALIDATE_SLOT0"):
            recovery.validate_contract(self.configs, self.layouts)

    def test_rtt_state_must_not_be_inherited_between_images(self):
        for image in self.configs:
            with self.subTest(image=image):
                configs = copy.deepcopy(self.configs)
                configs[image].pop("CONFIG_SEGGER_RTT_INIT_MODE_ALWAYS")
                with self.assertRaisesRegex(ValueError, "RTT_INIT_MODE_ALWAYS"):
                    recovery.validate_contract(configs, self.layouts)

    def test_boot_must_recover_when_application_is_missing(self):
        del self.configs["mcuboot"]["CONFIG_BOOT_FIRMWARE_LOADER_NO_APPLICATION"]
        with self.assertRaisesRegex(ValueError, "NO_APPLICATION"):
            recovery.validate_contract(self.configs, self.layouts)

    def test_loader_cannot_offer_direct_slot_upload_or_storage_erase(self):
        for option in ("CONFIG_MCUMGR_GRP_IMG_DIRECT_UPLOAD", "CONFIG_MCUMGR_GRP_ZBASIC"):
            with self.subTest(option=option):
                configs = copy.deepcopy(self.configs)
                configs["vimar_recovery"][option] = "y"
                with self.assertRaisesRegex(ValueError, option):
                    recovery.validate_contract(configs, self.layouts)

    def test_loader_requires_authenticated_writes(self):
        del self.configs["vimar_recovery"]["CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN"]
        with self.assertRaisesRegex(ValueError, "PERM_RW_AUTHEN"):
            recovery.validate_contract(self.configs, self.layouts)

    def test_wrong_loader_mode_is_rejected(self):
        self.configs["vimar_recovery"]["CONFIG_MCUBOOT_APPLICATION_FIRMWARE_UPDATER"] = "n"
        with self.assertRaisesRegex(ValueError, "APPLICATION_FIRMWARE_UPDATER"):
            recovery.validate_contract(self.configs, self.layouts)

    def test_multiple_upload_images_are_not_allowed(self):
        self.configs["vimar_recovery"]["CONFIG_MCUMGR_GRP_IMG_UPDATABLE_IMAGE_NUMBER"] = "2"
        with self.assertRaisesRegex(ValueError, "UPDATABLE_IMAGE_NUMBER"):
            recovery.validate_contract(self.configs, self.layouts)

    def test_mismatched_or_overlapping_layout_is_rejected(self):
        self.layouts["vimar_recovery"]["slot0_partition"] = (0xC000, 0xB0000)
        with self.assertRaisesRegex(ValueError, "partition map"):
            recovery.validate_contract(self.configs, self.layouts)

    def test_unsigned_boot_is_rejected(self):
        self.configs["mcuboot"]["CONFIG_BOOT_SIGNATURE_TYPE_NONE"] = "y"
        with self.assertRaisesRegex(ValueError, "SIGNATURE_TYPE_NONE"):
            recovery.validate_contract(self.configs, self.layouts)

    def test_combined_bluetooth_application_is_not_silently_accepted(self):
        self.configs["firmware"]["CONFIG_BT"] = "y"
        with self.assertRaisesRegex(ValueError, "CONFIG_BT"):
            recovery.validate_contract(self.configs, self.layouts)

    def image(self, base):
        header = struct.pack("<IIHHII", 0x96F3B83D, 0, 512, 0, 8, 0)
        return header.ljust(512, b"\0") + struct.pack("<II", 0x20040000, base + 513)

    def test_image_must_execute_from_its_own_slot(self):
        recovery.validate_image(self.image(0xB0000), 0xB0000, 0x40000)
        with self.assertRaisesRegex(ValueError, "reset vector"):
            recovery.validate_image(self.image(0xC000), 0xB0000, 0x40000)

    def test_image_must_reserve_fifteen_percent(self):
        with self.assertRaisesRegex(ValueError, "reserve"):
            recovery.validate_image(self.image(0xB0000).ljust(230000, b"\xff"),
                                    0xB0000, 0x40000)

    def test_corrupt_image_header_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "header"):
            recovery.validate_image(bytes(520), 0xB0000, 0x40000)

    def test_separately_signed_hex_can_have_different_signature_bytes(self):
        binary = self.image(0xB0000) + b"binary-signature"
        hex_data = self.image(0xB0000) + b"hex-signature"
        memory = {0xB0000 + i: byte for i, byte in enumerate(hex_data)}
        recovery.validate_merged_image(binary, memory, memory, 0xB0000, 0x40000)

    def test_merged_hex_must_contain_exact_signed_hex_and_same_payload(self):
        binary = self.image(0xB0000)
        memory = {0xB0000 + i: byte for i, byte in enumerate(binary)}
        changed = dict(memory)
        changed[0xB0000 + 519] ^= 2
        with self.assertRaisesRegex(ValueError, "merged HEX"):
            recovery.validate_merged_image(binary, memory, changed, 0xB0000, 0x40000)
        with self.assertRaisesRegex(ValueError, "payload"):
            recovery.validate_merged_image(binary, changed, changed, 0xB0000, 0x40000)


if __name__ == "__main__":
    unittest.main()
