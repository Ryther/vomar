import asyncio
import os
from unittest.mock import patch
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[1] / 'button_walkthrough.py'
spec = importlib.util.spec_from_file_location('button_walkthrough', PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class RecoveryValidationTests(unittest.TestCase):
    def test_name_or_wrong_active_slot_cannot_validate_recovery(self):
        for images in ([], [{'slot': 1, 'active': True, 'hash': 'wrong'}],
                       [{'slot': 0, 'active': True, 'hash': m.RECOVERY_HASH}]):
            with self.assertRaises(ValueError):
                m.validate_images(images)

    def test_checks_both_recovery_and_intact_main_hash(self):
        images = [{'slot': 1, 'active': True, 'hash': m.RECOVERY_HASH},
                  {'slot': 0, 'active': False, 'hash': m.MAIN_HASH}]
        m.validate_images(images)
        images[1]['hash'] = 'unexpected'
        with self.assertRaises(ValueError):
            m.validate_images(images)


class WalkthroughTests(unittest.IsolatedAsyncioTestCase):
    async def run_walkthrough(self, answers, failure=None, return_failure=None):
        class Probe:
            returns = 0
            async def main_status(self):
                return {'simulated': True, 'stock_output_enabled': False,
                        'software_recovery': True, 'output_fault': False}
            async def gesture(self, text, emit):
                emit('gesture_armed', instruction=text)
                if failure:
                    raise failure
                return [{'slot': 1, 'active': True, 'hash': m.RECOVERY_HASH},
                        {'slot': 0, 'active': False, 'hash': m.MAIN_HASH}]
            async def return_to_main(self, emit):
                self.returns += 1
                emit("reset_request_sending")
                emit("reset_acknowledged")
                if return_failure:
                    raise return_failure
                return await self.main_status()
        values = iter(answers)
        async def prompt(text):
            return next(values)
        with tempfile.TemporaryDirectory() as folder:
            journal = m.Journal(Path(folder))
            probe = Probe()
            code = await m.walkthrough(probe, journal, prompt)
            result = json.loads((Path(folder) / 'results.json').read_text())
            events = [json.loads(line) for line in (Path(folder) / 'events.jsonl').read_text().splitlines()]
            return code, result, events, probe.returns

    async def test_two_real_observations_and_confirmations_required_for_pass(self):
        code, result, events, returns = await self.run_walkthrough(['', 'si', '', '', 'si', ''])
        self.assertEqual(code, 0)
        self.assertEqual(result['outcome'], 'passed')
        self.assertEqual(returns, 2)
        self.assertEqual(result['single_button_events'], 'not_observable_in_current_firmware')
        self.assertEqual(sum(e['event'] == 'gesture_armed' for e in events), 2)
        self.assertEqual(sum(e['event'] == 'return_to_main_requested' for e in events), 2)

    async def test_timeout_persists_failure_and_does_not_reset_or_claim_success(self):
        code, result, events, returns = await self.run_walkthrough([''], TimeoutError('no rescue'))
        self.assertNotEqual(code, 0)
        self.assertEqual(result['steps']['runtime_both']['outcome'], 'failed')
        self.assertEqual(result['steps']['power_up']['outcome'], 'not_run')
        self.assertEqual(returns, 0)
        self.assertIn('TimeoutError', result['steps']['runtime_both']['error'])

    async def test_skipping_is_incomplete(self):
        code, result, events, returns = await self.run_walkthrough(['salta', 'salta'])
        self.assertEqual(code, 2)
        self.assertEqual(result['outcome'], 'incomplete')
        self.assertEqual(returns, 0)

    async def test_operator_denial_is_not_physical_success(self):
        code, result, events, returns = await self.run_walkthrough(['', 'no', '', 'salta'])
        self.assertEqual(code, 2)
        self.assertEqual(result['steps']['runtime_both']['outcome'], 'unconfirmed')
        self.assertEqual(returns, 1)

    async def test_interruption_keeps_partial_results(self):
        code, result, events, returns = await self.run_walkthrough([''], KeyboardInterrupt())
        self.assertEqual(code, 130)
        self.assertEqual(result['steps']['runtime_both']['outcome'], 'cancelled')
        self.assertEqual(result['outcome'], 'cancelled')
        self.assertEqual(returns, 0)

    async def test_unconfirmed_return_prompt_sends_no_reset(self):
        code, result, events, returns = await self.run_walkthrough(['', 'si', 'no'])
        self.assertEqual(code, 1)
        self.assertEqual(returns, 0)

    async def test_real_async_cancellation_preserves_report(self):
        code, result, events, returns = await self.run_walkthrough([''], asyncio.CancelledError())
        self.assertEqual(code, 130)
        self.assertEqual(result['outcome'], 'cancelled')
        self.assertEqual(result['steps']['runtime_both']['outcome'], 'cancelled')

    async def test_terminal_cancellation_removes_reader(self):
        read_fd, write_fd = os.pipe()
        try:
            with os.fdopen(read_fd) as terminal, patch.object(m.sys, 'stdin', terminal):
                task = asyncio.create_task(m.terminal_prompt('Test prompt'))
                await asyncio.sleep(0)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertFalse(asyncio.get_running_loop().remove_reader(read_fd))
        finally:
            os.close(write_fd)

    async def test_cancel_during_return_keeps_reset_evidence(self):
        code, result, events, returns = await self.run_walkthrough(
            ['', 'si', ''], return_failure=asyncio.CancelledError())
        self.assertEqual(code, 130)
        self.assertTrue(result['steps']['runtime_both']['return_requested'])
        self.assertIn('reset_acknowledged', [e['event'] for e in events])

class StartupReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_transient_unavailability_is_retried_before_main_is_accepted(self):
        calls = []
        async def read():
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError('not advertising yet')
            return {'simulated': True, 'software_recovery': True,
                    'stock_output_enabled': False, 'output_fault': False}
        events = []
        result = await m.wait_for_main(read, 1, lambda event, **kw: events.append(event), delay=0)
        self.assertTrue(result['simulated'])
        self.assertEqual(len(calls), 3)
        self.assertEqual(events.count('main_wait_retry'), 2)

    async def test_wrong_profile_is_not_retried(self):
        async def read():
            return {'simulated': False, 'software_recovery': True,
                    'stock_output_enabled': True, 'output_fault': False}
        with self.assertRaises(ValueError):
            await m.wait_for_main(read, 1, lambda *a, **k: None, delay=0)

    async def test_timeout_is_not_accepted_as_ready(self):
        async def read():
            await asyncio.sleep(1)
        with self.assertRaises(TimeoutError):
            await m.wait_for_main(read, .01, lambda *a, **k: None, delay=0)

    async def test_power_up_instructions_keep_up_held_until_detection(self):
        text = dict((key, instruction) for key, _, instruction in m.STEPS)['power_up']
        self.assertNotIn('2 secondi', text)
        self.assertIn('finché', text)
