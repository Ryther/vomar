import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).parents[1] / "triage_targets.py"


def module():
    if not MODULE_PATH.is_file():
        raise AssertionError(f"missing triage module: {MODULE_PATH}")
    spec = importlib.util.spec_from_file_location("target_triage", MODULE_PATH)
    loaded = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(loaded)
    return loaded


class TargetTriageTests(unittest.TestCase):
    def test_scalar_constant_alone_remains_hypothesis(self):
        result = module().score_signals(
            "button", memory_peripherals=(), scalar_peripherals=("GPIO",),
            strings=(), neighbor=False, match_score=0,
        )
        self.assertEqual(result.classification, "HYPOTHESIS")
        self.assertLess(result.score, 10)

    def test_independent_memory_and_string_signals_are_strong_inference(self):
        result = module().score_signals(
            "led", memory_peripherals=("PWM0",), scalar_peripherals=(),
            strings=("status led update",), neighbor=False, match_score=0,
        )
        self.assertEqual(result.classification, "STRONG INFERENCE")
        self.assertIn("memory:PWM0", result.signals)
        self.assertIn("string:led", result.signals)

    def test_match_and_neighbor_cannot_confirm_semantics(self):
        result = module().score_signals(
            "secondary_mcu", memory_peripherals=(), scalar_peripherals=(),
            strings=(), neighbor=True, match_score=100,
        )
        self.assertEqual(result.classification, "HYPOTHESIS")

    def test_target_keywords_are_specific(self):
        self.assertTrue(module().matches_keyword("fault_watchdog", "watchdog timeout"))
        self.assertFalse(module().matches_keyword("button", "buttonless dfu"))
        self.assertTrue(module().matches_keyword("button", "local button press"))


if __name__ == "__main__":
    unittest.main()
