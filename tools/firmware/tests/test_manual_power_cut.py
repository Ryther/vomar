import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / 'manual_power_cut.py'
spec = importlib.util.spec_from_file_location('manual_power_cut', PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class InterruptedUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_signal_then_keep_uploading_until_disconnect(self):
        seen = []

        async def offsets():
            for value in (1024, 65536, 68000):
                seen.append(value)
                yield value
            raise ConnectionError('USB removed')

        result = await module.cut_window(offsets(), 100000, 65536,
                                         lambda *args, **kw: seen.append(args[0]))
        self.assertEqual(result['outcome'], 'upload_interrupted_after_signal')
        self.assertIn(68000, seen)
        self.assertEqual(seen.count('cut_now'), 1)

    async def test_early_disconnect_is_not_a_valid_cut(self):
        async def offsets():
            yield 1024
            raise ConnectionError('early failure')

        with self.assertRaises(ConnectionError):
            await module.cut_window(offsets(), 100000, 65536, lambda *a, **k: None)

    async def test_abort_before_completion_if_user_does_not_cut(self):
        async def offsets():
            for value in (65536, 85000, 91000, 100000):
                yield value

        result = await module.cut_window(offsets(), 100000, 65536, lambda *a, **k: None)
        self.assertEqual(result['outcome'], 'no_cut_observed')
        self.assertEqual(result['acknowledged'], 91000)
