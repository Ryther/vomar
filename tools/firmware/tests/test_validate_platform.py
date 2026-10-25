import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
VALIDATOR = REPO / "tools/firmware/validate_platform.py"
FW = REPO / "firmware"
sys.path.insert(0, str(REPO / "tools/firmware"))
from validate_platform import parse_partitions, validate_resource_budget


class PlatformValidationTests(unittest.TestCase):
    def test_resource_budget_reserves_fifteen_percent(self):
        validate_resource_budget(85, 85, 100, 100)
        with self.assertRaisesRegex(ValueError, "flash budget"):
            validate_resource_budget(86, 85, 100, 100)
        with self.assertRaisesRegex(ValueError, "RAM budget"):
            validate_resource_budget(85, 86, 100, 100)

    def test_source_contract_passes(self):
        result = subprocess.run(
            ["python3", str(VALIDATOR), "--source", str(FW)],
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("source contract: valid", result.stdout)

    def test_zigbee_partitions_match_nrf52840_add_on_requirements(self):
        partitions = {
            name: (address, size)
            for name, address, size in parse_partitions(FW / "pm_static.yml")
        }
        self.assertEqual(partitions["zboss_nvram"], (0xF7000, 0x8000))
        self.assertEqual(partitions["zboss_product_config"], (0xFF000, 0x1000))

    def test_overlap_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            for name in ("pm_static.yml", "sysbuild.conf"):
                (source / name).write_text((FW / name).read_text(encoding="utf-8"), encoding="utf-8")
            text = (source / "pm_static.yml").read_text(encoding="utf-8")
            (source / "pm_static.yml").write_text(text.replace("address: 0x0007e000", "address: 0x00070000"), encoding="utf-8")
            result = subprocess.run(
                ["python3", str(VALIDATOR), "--source", str(source)],
                text=True, capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("overlap", result.stderr)

    def test_build_image_version_must_match_source_version(self):
        build = REPO / "work/build-platform"
        if not (build / "firmware/zephyr/zephyr.signed.bin").is_file():
            self.skipTest("validated platform build is unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            for name in ("pm_static.yml", "sysbuild.conf", "VERSION"):
                (source / name).write_text(
                    (FW / name).read_text(encoding="utf-8"), encoding="utf-8"
                )
            version = (source / "VERSION").read_text(encoding="utf-8")
            (source / "VERSION").write_text(
                version.replace("PATCHLEVEL = 2", "PATCHLEVEL = 99"),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    "python3",
                    str(VALIDATOR),
                    "--source",
                    str(source),
                    "--build-dir",
                    str(build),
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("image version", result.stderr)

    def test_private_key_is_ignored_and_public_key_is_tracked(self):
        ignore = (REPO / ".gitignore").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory)
            (checkout / ".gitignore").write_text(ignore, encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(checkout)], check=True)
            ignored = subprocess.run(
                ["git", "check-ignore", "--no-index", "firmware/keys/dev-private.pem"],
                cwd=checkout, capture_output=True,
            )
            self.assertEqual(ignored.returncode, 0)
            for name in ("firmware/keys/dev-public.pem", "firmware/keys/README.md"):
                visible = subprocess.run(
                    ["git", "check-ignore", "--no-index", name],
                    cwd=checkout, capture_output=True,
                )
                self.assertEqual(visible.returncode, 1, name)
        public = (FW / "keys/dev-public.pem").read_text(encoding="ascii")
        self.assertIn("BEGIN PUBLIC KEY", public)
        sysbuild = (FW / "sysbuild.conf").read_text(encoding="utf-8")
        self.assertIn("SB_CONFIG_BOOT_SIGNATURE_TYPE_ECDSA_P256=y", sysbuild)
        self.assertIn("keys/dev-private.pem", sysbuild)


if __name__ == "__main__":
    unittest.main()
