import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest


MODULE_PATH = Path(__file__).parents[1] / "preflight.py"


def load_preflight():
    if not MODULE_PATH.is_file():
        raise AssertionError(f"missing production module: {MODULE_PATH}")
    spec = importlib.util.spec_from_file_location("ghidra_preflight", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo = Path(self.tempdir.name)
        firmware = self.repo / "inputs" / "test.bin"
        firmware.parent.mkdir(parents=True)
        self.data = struct.pack("<II", 0x20001000, 0x00026009) + bytes(24)
        firmware.write_bytes(self.data)
        self.target = {
            "name": "test",
            "source_path": "inputs/test.bin",
            "sha256": hashlib.sha256(self.data).hexdigest(),
            "size": len(self.data),
            "image_base": "0x00026000",
            "reset_handler": "0x00026008",
        }

    def tearDown(self):
        self.tempdir.cleanup()

    def validate(self, **changes):
        target = self.target | changes
        return load_preflight().validate_target(self.repo, target)

    def test_valid_vector_and_evidence_return_normalized_values(self):
        result = self.validate()
        self.assertEqual(result["initial_sp"], 0x20001000)
        self.assertEqual(result["reset_vector"], 0x00026009)
        self.assertEqual(result["reset_handler"], 0x00026008)
        self.assertEqual(result["source_path"], "inputs/test.bin")

    def test_wrong_hash_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            self.validate(sha256="0" * 64)

    def test_wrong_size_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "size mismatch"):
            self.validate(size=len(self.data) + 1)

    def test_stack_pointer_outside_nrf52840_sram_is_rejected(self):
        data = struct.pack("<II", 0x20040004, 0x00026009) + bytes(24)
        path = self.repo / "inputs" / "test.bin"
        path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "initial stack pointer"):
            self.validate(sha256=hashlib.sha256(data).hexdigest())

    def test_reset_vector_without_thumb_bit_is_rejected(self):
        data = struct.pack("<II", 0x20001000, 0x00026008) + bytes(24)
        path = self.repo / "inputs" / "test.bin"
        path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "Thumb bit"):
            self.validate(sha256=hashlib.sha256(data).hexdigest())

    def test_reset_handler_outside_loaded_image_is_rejected(self):
        data = struct.pack("<II", 0x20001000, 0x00027001) + bytes(24)
        path = self.repo / "inputs" / "test.bin"
        path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "outside loaded image"):
            self.validate(
                sha256=hashlib.sha256(data).hexdigest(),
                reset_handler="0x00027000",
            )

    def test_manifest_requires_named_target_mapping(self):
        manifest = self.repo / "manifest.json"
        manifest.write_text(json.dumps({"targets": []}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "targets"):
            load_preflight().load_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
