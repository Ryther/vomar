import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / 'watch_vimar_swd.py'
spec = importlib.util.spec_from_file_location('watch_vimar_swd', PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ContactMessages(unittest.TestCase):
    def test_missing_probe_is_not_reported_as_bad_contact(self):
        self.assertIn('DK/J-Link non rilevato via USB', m.failure_message('Error: No J-Link device found'))

    def test_swd_failure_distinguished_from_usb_failure(self):
        msg = m.failure_message('Info : VTarget = 3.300 V\nError: Error connecting DP: cannot read IDR')
        self.assertIn('J-Link presente', msg)
        self.assertIn('3.300 V', msg)
        self.assertIn('SWD non risponde', msg)

    def test_busy_probe_does_not_suggest_moving_contacts(self):
        self.assertIn('occupato', m.failure_message('Error: Cannot connect to J-Link via USB. Device is already opened.'))

    def test_partial_debug_response_is_visible_without_claiming_vimar_identity(self):
        msg = m.failure_message('Info : SWD DPIDR 0x2ba01477')
        self.assertIn('RISPOSTA PARZIALE', msg)
        self.assertIn('identità Vimar non letta', msg)

    def test_parity_error_is_distinguished(self):
        msg = m.failure_message('Error: SWD: Read data parity mismatch\nInfo : SWD DPIDR 0x2ba01477')
        self.assertIn('parità', msg)

    def test_process_signal_is_reported(self):
        msg = m.failure_message('Info : SWD DPIDR 0x2ba01477', -11)
        self.assertIn('segnale 11', msg)

class CaptureGuardTests(unittest.TestCase):
    def test_guard_captures_only_known_vimar(self):
        import subprocess
        import tempfile
        for uid, expected in [('0x11223344 0x55667788', True),
                              ('0x31415926 0x27182818', False)]:
            script = ('proc read_memory {args} {return {' + uid + '}}\n'
                      'proc dump_image {args} {puts CAPTURED}\n'
                      'proc mdw {args} {}\n' + '\n'.join(m.capture_commands(Path('/tmp/capture-test'), (0x11223344, 0x55667788))))
            with tempfile.TemporaryDirectory() as folder:
                p = Path(folder)/'guard.tcl'
                p.write_text(script)
                result = subprocess.run(['tclsh', str(p)], capture_output=True, text=True)
            self.assertEqual('CAPTURED' in result.stdout, expected)
            self.assertEqual(result.returncode == 0, expected)

    def test_capture_contains_no_execution_or_flash_mutation_commands(self):
        commands = m.capture_commands(Path('/tmp/capture-test'), (0x11223344, 0x55667788))
        for word in ('halt', 'resume', 'reset', 'program', 'erase', 'write_memory'):
            self.assertFalse(any(c.split()[0] == word for c in commands))
