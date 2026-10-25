import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).parents[1] / "match_firmware_functions.py"


def module():
    if not MODULE_PATH.is_file():
        raise AssertionError(f"missing matcher: {MODULE_PATH}")
    spec = importlib.util.spec_from_file_location("function_matcher", MODULE_PATH)
    loaded = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(loaded)
    return loaded


class FirmwareFunctionMatcherTests(unittest.TestCase):
    def feature(self, address, **changes):
        values = dict(
            address=address, byte_size=100, instruction_count=40, basic_blocks=5,
            cyclomatic=3, calls=4, unique_constants=8,
            mnemonic_sha256="a" * 64, exact_bytes_sha256="b" * 64,
        )
        values.update(changes)
        return module().FunctionFeatures(**values)

    def test_exact_bytes_outrank_mnemonic_only(self):
        mesh = self.feature("0x00001000")
        exact = module().score_pair(mesh, self.feature("0x00002000"))
        mnemonic = module().score_pair(
            mesh, self.feature("0x00003000", exact_bytes_sha256="c" * 64)
        )
        self.assertGreater(exact.score, mnemonic.score)
        self.assertIn("exact_bytes", exact.evidence)

    def test_structure_alone_cannot_reach_high_confidence(self):
        mesh = self.feature("0x00001000")
        other = self.feature(
            "0x00002000", mnemonic_sha256="c" * 64, exact_bytes_sha256="d" * 64
        )
        result = module().score_pair(mesh, other)
        self.assertLess(result.score, 50)
        self.assertNotIn("exact_bytes", result.evidence)

    def test_conflicting_size_reduces_score(self):
        mesh = self.feature("0x00001000")
        close = module().score_pair(
            mesh, self.feature("0x00002000", exact_bytes_sha256="c" * 64)
        )
        far = module().score_pair(
            mesh,
            self.feature(
                "0x00003000", byte_size=500, instruction_count=200,
                exact_bytes_sha256="c" * 64,
            ),
        )
        self.assertLess(far.score, close.score)
        self.assertIn("size_ratio", far.conflicts)

    def test_rank_candidates_is_deterministic_and_limited(self):
        mesh = [self.feature("0x00001000")]
        zigbee = [self.feature(f"0x{address:08x}") for address in (0x3000, 0x2000, 0x4000)]
        ranked = module().rank_candidates(mesh, zigbee, limit_per_function=2)
        self.assertEqual(len(ranked), 2)
        self.assertEqual([row.zigbee_address for row in ranked], ["0x00002000", "0x00003000"])


if __name__ == "__main__":
    unittest.main()
