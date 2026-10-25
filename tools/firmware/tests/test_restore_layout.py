"""Host-only layout safety checks; no probe or hardware dependency."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('restore_layout', Path(__file__).parents[1] / 'restore_layout.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class RestoreLayoutTests(unittest.TestCase):
    def reference(self):
        data = bytearray(b'\x33' * m.SIZE)
        data[m.SCRATCH_START:m.SCRATCH_END] = b'\xff' * (m.SCRATCH_END-m.SCRATCH_START)
        return data

    def test_full_coverage_and_interruptions(self):
        result = m.simulate(self.reference())
        self.assertEqual(result['pages'], 256)
        self.assertTrue(result['final_byte_identical'])
        self.assertGreater(result['interruption_checkpoints']['boot_transition'], 0)
        self.assertGreater(result['interruption_checkpoints']['stock_boot_complete_cleanup_pending'], 0)

    def test_rejects_one_non_erased_scratch_byte(self):
        reference = self.reference()
        reference[m.SCRATCH_END-1] = 0
        with self.assertRaises(ValueError):
            m.simulate(reference)

    def test_last_page_and_ef000_are_streamed(self):
        addresses = {a for phase, a, _, _ in m.operations(self.reference()) if phase == 'stream'}
        self.assertIn(0xef000, addresses)
        self.assertIn(0xff000, addresses)
        self.assertNotIn(m.SCRATCH_END-m.PAGE, addresses)

    def test_entire_boot_is_erased_before_any_boot_program(self):
        boot = [op for op in m.operations(self.reference()) if op[0] == 'boot']
        first_program = next(i for i, op in enumerate(boot) if op[2] == 'program')
        self.assertEqual([op[1] for op in boot[:first_program]],
                         list(range(0, m.BOOT_END, m.PAGE)))
        self.assertTrue(all(op[2] == 'erase' for op in boot[:first_program]))
        self.assertTrue(all(op[2] == 'program' for op in boot[first_program:]))

    def test_rejects_partial_backup(self):
        with self.assertRaises(ValueError):
            m.validate(bytes(m.SIZE-1))


if __name__ == '__main__':
    unittest.main()
