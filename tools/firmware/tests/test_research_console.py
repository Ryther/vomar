import importlib.util
from pathlib import Path
import struct
import unittest

spec = importlib.util.spec_from_file_location('research_console',
    Path(__file__).resolve().parents[1] / 'research_console.py')
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


class ConsoleCodecTests(unittest.TestCase):
    def test_signed_level_and_response_correlation(self):
        self.assertEqual(client.encode(1, 42, -32768), b'\x01\x01*\0\0\x80\xff\xff')
        response = struct.pack('<BBHiiII', 1, 1, 42, 0, -32768, 1000, 3)
        decoded = client.decode(response, 1, 42)
        self.assertTrue(decoded['simulated'])
        self.assertTrue(decoded['software_recovery'])
        self.assertFalse(decoded['stock_output_enabled'])
        with self.assertRaises(ValueError):
            client.decode(response, 1, 43)
        with self.assertRaises(ValueError):
            client.decode(response[:-1], 1, 42)
        with self.assertRaises(ValueError):
            client.encode(1, 42, 32768)

    def test_device_error_is_not_reported_as_success(self):
        response = struct.pack('<BBHiiII', 1, 1, 42, -34, -32768, 1000, 1)
        with self.assertRaises(RuntimeError):
            client.decode(response, 1, 42)
