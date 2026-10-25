from local_inputs import local_input, sdk_root
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tools/firmware/verify_nordic_dfu_signatures.py"
MESH_DAT = ROOT / "inputs/firmware/mesh/P561_Dimmer_Mesh.dat"
ZIGBEE_DAT = ROOT / "inputs/firmware/zigbee/P561_Dimmer_Zigbee.dat"

# Public-key coordinates in the little-endian format embedded by Nordic SDK.
STOCK_PUBLIC_KEY = (
    "51cf92bca6d5d257283efa7d07f4495514b65ff4e63c04d45dfe55374d0062f"
    "0c804ecc0e5bf53286be247d2e825ecc7fc37313b6eff5e3907de99abef8c0548"
)
SHIFTED_NON_KEY = (
    "a6d5d257283efa7d07f4495514b65ff4e63c04d45dfe55374d0062f0c804ecc0"
    "e5bf53286be247d2e825ecc7fc37313b6eff5e3907de99abef8c054831383838"
)


class VerifyNordicDfuSignaturesCliTests(unittest.TestCase):
    def run_tool(self, key: str):
        local_input(MESH_DAT)
        local_input(ZIGBEE_DAT)
        return subprocess.run(
            [
                sys.executable,
                str(TOOL),
                "--public-key-le",
                key,
                "--json",
                str(MESH_DAT),
                str(ZIGBEE_DAT),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def test_verifies_both_stock_init_packets_with_embedded_key(self):
        result = self.run_tool(STOCK_PUBLIC_KEY)

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["public_key_le"], STOCK_PUBLIC_KEY)
        self.assertEqual(
            [(Path(item["path"]).name, item["verified"]) for item in report["packets"]],
            [("P561_Dimmer_Mesh.dat", True), ("P561_Dimmer_Zigbee.dat", True)],
        )

    def test_rejects_the_previously_shifted_64_byte_candidate(self):
        result = self.run_tool(SHIFTED_NON_KEY)

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stdout, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["public_key_le"], SHIFTED_NON_KEY)
        self.assertEqual(
            [item["verified"] for item in report["packets"]],
            [False, False],
        )


if __name__ == "__main__":
    unittest.main()
