import asyncio
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[1] / 'measure_boot.py'
spec = importlib.util.spec_from_file_location('measure_boot', PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class TimingTests(unittest.TestCase):
    def test_measurement_is_bounded_by_cue_and_manual_confirmation(self):
        self.assertEqual(m.latency_bounds(10, 12, 20), {'lower_seconds': 8, 'upper_seconds': 10})

    def test_advertising_before_enter_does_not_produce_negative_boot_time(self):
        self.assertEqual(m.latency_bounds(10, 14, 11), {'lower_seconds': 0, 'upper_seconds': 1})

    def test_impossible_order_is_rejected(self):
        with self.assertRaises(ValueError):
            m.latency_bounds(10, 9, 20)
        with self.assertRaises(ValueError):
            m.latency_bounds(10, 12, 9)

    def test_uptime_distinguishes_old_process_from_new_kernel(self):
        before = {'request_start': 100, 'response_end': 101, 'uptime_ms': 90000}
        old = {'request_start': 150, 'response_end': 151, 'uptime_ms': 140000}
        new = {'request_start': 150, 'response_end': 151, 'uptime_ms': 20000}
        self.assertFalse(m.new_kernel_observed(before, old, 125))
        self.assertTrue(m.new_kernel_observed(before, new, 125))

    def test_dk_and_pre_cue_advertisements_are_not_counted(self):
        t = m.Advertisements()
        t.arm(10)
        t.observe('C0:00:00:00:00:99', 11, 'Vimar30805-Lab')
        t.observe(m.ADDRESS, 9, 'Vimar30805-Lab')
        self.assertIsNone(t.first)
        t.observe(m.ADDRESS, 12, 'Vimar30805-Lab')
        t.observe(m.ADDRESS, 13, 'Vimar30805-Lab')
        self.assertEqual(t.first['observed_at'], 12)

    def test_journal_does_not_overwrite_and_keeps_partial_state(self):
        with tempfile.TemporaryDirectory() as d:
            j = m.Journal(Path(d))
            j.result['outcome'] = 'cancelled'
            j.emit('operator_off_confirmed')
            j.save()
            self.assertEqual(json.loads((Path(d)/'results.json').read_text())['outcome'], 'cancelled')
            self.assertIn('operator_off_confirmed', (Path(d)/'events.jsonl').read_text())
            with self.assertRaises(FileExistsError):
                m.Journal(Path(d))


class ReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_are_logged_until_authenticated_response(self):
        calls = []
        async def read():
            calls.append(1)
            if len(calls) < 2:
                raise RuntimeError('not ready')
            return {'uptime_ms': 1000, 'simulated': True, 'software_recovery': True,
                    'stock_output_enabled': False, 'output_fault': False}
        events = []
        result = await m.wait_status(read, 1, lambda e, **k: events.append(e), delay=0)
        self.assertEqual(result['uptime_ms'], 1000)
        self.assertIn('ble_retry', events)

    async def test_wrong_profile_is_not_counted_as_ready(self):
        async def read():
            return {'simulated': False, 'software_recovery': True,
                    'stock_output_enabled': True, 'output_fault': False}
        with self.assertRaises(ValueError):
            await m.wait_status(read, 1, lambda *a, **k: None, delay=0)

    async def test_no_response_is_timeout_not_success(self):
        async def read():
            await asyncio.sleep(1)
        with self.assertRaises(TimeoutError):
            await m.wait_status(read, .01, lambda *a, **k: None)

class ConnectionHandoffTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_stops_before_connecting_to_exact_discovered_device(self):
        events = []
        device = object()
        class Scanner:
            running = True
            async def stop(self):
                self.running = False
                events.append('stop')
        scanner = Scanner()
        class Probe:
            async def read(self, selected):
                if scanner.running:
                    raise RuntimeError('Operation already in progress')
                assert selected is device
                events.append('read')
                return {'simulated': True, 'software_recovery': True,
                        'stock_output_enabled': False, 'output_fault': False}
        result = await m.read_after_discovery(scanner, Probe(), device, 1, lambda *a, **k: None,
                                               delay=0)
        self.assertTrue(result['simulated'])
        self.assertEqual(events, ['stop', 'read'])

    async def test_inprogress_cancels_only_pending_target_connection_before_retry(self):
        events = []
        device = object()
        class InProgress(RuntimeError):
            dbus_error = 'org.bluez.Error.InProgress'
        class Scanner:
            async def stop(self): pass
        class Probe:
            n = 0
            async def read(self, selected):
                self.n += 1
                if self.n == 1:
                    raise InProgress('busy')
                events.append('read')
                return {'simulated': True, 'software_recovery': True,
                        'stock_output_enabled': False, 'output_fault': False}
            async def cancel_pending(self, selected):
                assert selected is device
                events.append('cancel_pending')
        await m.read_after_discovery(Scanner(), Probe(), device, 1, lambda *a, **k: None,
                                    delay=0)
        self.assertEqual(events, ['cancel_pending', 'read'])

class PowerOffObservationTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, hold, quiet, advertisements):
        now = [100.0]
        tracker = m.Advertisements()
        tracker.observe(m.ADDRESS, 99, 'Vimar30805-Lab')
        reports, events = [], []
        async def pause(seconds):
            now[0] += seconds
            if now[0] in advertisements:
                tracker.observe(m.ADDRESS, now[0], 'Vimar30805-Lab')
        result = await m.wait_for_power_off(
            tracker, 100, hold, quiet, 1,
            lambda event, **data: events.append((event, data)), reports.append,
            clock=lambda: now[0], pause=pause)
        return result, reports, events

    async def test_quiet_radio_does_not_shorten_minimum_discharge_wait(self):
        result, reports, events = await self.exercise(12, 3, set())
        self.assertGreaterEqual(result['elapsed_seconds'], 12)
        self.assertGreaterEqual(result['silence_seconds'], 3)
        self.assertFalse(result['electrical_power_off_confirmed'])
        self.assertEqual(events[-1][0], 'power_off_observation_completed')

    async def test_late_advertisement_restarts_silence_window(self):
        result, reports, events = await self.exercise(5, 4, {104.0})
        self.assertGreaterEqual(result['elapsed_seconds'], 8)
        self.assertEqual(result['last_advertisement_at'], 104)
        self.assertTrue(any(r['advertisement_after_off_confirmation'] for r in reports))

    async def test_incomplete_observation_times_out_instead_of_claiming_off(self):
        tracker = m.Advertisements()
        with self.assertRaises(TimeoutError):
            await m.wait_for_power_off(tracker, m.time.monotonic(), 1000, 10, .01,
                                      lambda *a, **k: None, lambda *a: None)

    async def test_only_exact_vimar_counts_as_target_observation(self):
        tracker = m.Advertisements()
        tracker.observe('C0:00:00:00:00:99', 101, 'Vimar30805-Lab')
        self.assertEqual(tracker.count, 0)
        tracker.observe(m.ADDRESS, 102, 'Vimar30805-Lab')
        self.assertEqual(tracker.count, 1)

class RecoveryDetectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_recovery_is_reported_immediately_without_retrying_main_until_timeout(self):
        calls = []
        async def read():
            calls.append(1)
            raise m.RecoveryDetected('Recovery presente')
        with self.assertRaises(m.RecoveryDetected):
            await m.wait_status(read, 1, lambda *a, **k: None, delay=0)
        self.assertEqual(len(calls), 1)

    def test_service_uuid_identifies_recovery_without_trusting_advertising_name(self):
        self.assertEqual(m.firmware_mode(['8d53dc1d-1db7-4cd3-868b-8a527460aa84']), 'recovery')
        self.assertEqual(m.firmware_mode(['fde30805-c001-4a40-8d00-308050000001']), 'main')
        self.assertEqual(m.firmware_mode(['00001800-0000-1000-8000-00805f9b34fb']), 'unknown')
