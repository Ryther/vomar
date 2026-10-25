"""Recorded OFF readback must not be confused with loss of remembered brightness."""
import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('fade',Path(__file__).resolve().parents[1]/'fade_walkthrough.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class RestoreTests(unittest.TestCase):
 def test_off_can_report_zero_brightness_while_target_remembers_level(self):
  original={'state':'OFF','brightness':1}
  final={'state':'OFF','brightness':0,'target_level':1,'fault_code':0}
  self.assertTrue(m.restored_state_matches(original,final))
  self.assertFalse(m.restored_state_matches(original,{**final,'target_level':82}))
  self.assertFalse(m.restored_state_matches(original,{**final,'fault_code':1}))
  self.assertFalse(m.restored_state_matches(original,{**final,'state':'ON'}))
 def test_off_baseline_uses_remembered_target_and_on_requires_actual_brightness(self):
  original={'state':'OFF','brightness':0,'target_level':73}
  self.assertTrue(m.restored_state_matches(original,{'state':'OFF','brightness':0,'target_level':73,'fault_code':0}))
  original={'state':'ON','brightness':73,'target_level':73}
  self.assertTrue(m.restored_state_matches(original,{**original,'fault_code':0}))
  self.assertFalse(m.restored_state_matches(original,{**original,'brightness':0,'fault_code':0}))

class Journal:
 def __init__(self):self.result={'observations':{},'commands':[]};self.events=[]
 def save(self):pass
 def emit(self,event,**data):self.events.append((event,data))

class FakeProbe:
 def __init__(self):
  self.state={**{k:0 for k in m.CONFIG+m.STATUS},'schema_version':5,'output_mode':'dimmable',
   'state':'OFF','brightness':0,'target_level':73,'min_level':1,'max_level':254,
   'rise_transition_ms':1000,'fall_transition_ms':1000,'ramp_start_level':1,'ramp_end_level':1,
   'auto_off_mode':'disabled','timer_active':False,'transition_active':False,'applied_output_on':'OFF',
   'p031_enabled':True,'p031_sample_valid':True,'p031_output_blocked':False,'p031_trip_count':0}
  self.device={'friendly_name':'Test dimmer'};self.calls=[]
 async def read(self,keys):return dict(self.state)
 async def set(self,payload,on,level=None):
  self.calls.append(dict(payload));self.state.update(state='ON' if on else 'OFF',
   applied_output_on='ON' if on else 'OFF',brightness=level if on else 0,
   applied_output_level=level if on else 0,transition_active=False)
  if on:self.state['target_level']=level

class StartupTests(unittest.IsolatedAsyncioTestCase):
 async def test_real_probe_guard_prevents_second_command_after_transient_trip(self):
  import json
  from datetime import datetime,timezone
  from types import SimpleNamespace
  from unittest.mock import patch,AsyncMock
  j=Journal();p=m.Probe('secret',5,j);p.state=FakeProbe().state
  p.expected_protection_trips=0
  async def sent(raw):
   frame=json.loads(raw);self.assertEqual(frame['topic'],m.IEEE+'/set')
   level=frame['payload']['brightness']
   p.observe_state({**p.state,'state':'ON','applied_output_on':'ON','applied_output_level':level,
    'transition_active':False,'last_seen':datetime.now(timezone.utc).isoformat()})
  p.ws=SimpleNamespace(send=AsyncMock(side_effect=sent))
  async def transient(_):
   p.observe_state({**p.state,'p031_sample_valid':False})
   p.observe_state({**p.state,'p031_sample_valid':True})
  with patch.object(m.asyncio,'sleep',transient):
   with self.assertRaisesRegex(RuntimeError,'P0.31'):await m.run_startup_trial(p,j,82,1,100)
  self.assertEqual(p.ws.send.await_count,1)
  self.assertEqual(len(j.result['commands']),1)
 async def test_default_target_uses_remembered_level_when_off_reports_zero(self):
  p=FakeProbe();j=Journal()
  _,target=await m.prepare_comparison(p,j)
  self.assertEqual(target,73)
 async def test_startup_trial_rejects_lamp_no_longer_off(self):
  p=FakeProbe();j=Journal();p.state.update(state='ON',applied_output_on='ON')
  with self.assertRaisesRegex(RuntimeError,'spenta'):await m.run_startup_trial(p,j,82,1,100)
  self.assertEqual(p.calls,[])
 async def test_reference_rejects_external_on_during_operator_pause(self):
  from unittest.mock import patch,AsyncMock
  p=FakeProbe();j=Journal()
  async def enter(text):
   if text.startswith('A2'):p.state.update(state='ON',applied_output_on='ON')
  with patch.object(m,'enter',enter),patch.object(m.asyncio,'sleep',new_callable=AsyncMock):
   with self.assertRaisesRegex(RuntimeError,'spenta'):await m.startup_walkthrough(p,j,(100,),32.3)
  self.assertEqual(p.calls,[])
 async def test_minimum_confirmation_precedes_additional_hold_then_same_target(self):
  from unittest.mock import patch
  p=FakeProbe();j=Journal();order=[];original_set=p.set
  async def set_(payload,on,level=None):
   order.append(('set',payload));await original_set(payload,on,level)
  async def wait(seconds):order.append(('wait',seconds))
  p.set=set_
  with patch.object(m.asyncio,'sleep',wait):await m.run_startup_trial(p,j,82,1,300)
  self.assertEqual(order,[('set',{'state':'ON','brightness':1,'transition':0}),('wait',.3),('set',{'state':'ON','brightness':82})])
  timing=j.result['startup_timings'][0]
  self.assertEqual(timing['additional_hold_requested_ms'],300)
  self.assertGreaterEqual(timing['send_gap_ms'],timing['minimum_confirmation_ms'])
  self.assertFalse(timing['physical_hold_measured'])
 async def test_minimum_report_does_not_have_to_include_target_level(self):
  from unittest.mock import patch,AsyncMock
  p=FakeProbe();j=Journal();original_set=p.set
  async def set_(payload,on,level=None):
   await original_set(payload,on,level);p.state['target_level']=73
  p.set=set_
  with patch.object(m.asyncio,'sleep',new_callable=AsyncMock):
   await m.run_startup_trial(p,j,82,1,100)
  self.assertEqual(len(p.calls),2)
 async def test_cancel_during_hold_never_sends_target_or_restore(self):
  import asyncio
  from unittest.mock import patch
  p=FakeProbe();j=Journal()
  async def cancel(_):raise asyncio.CancelledError()
  with patch.object(m.asyncio,'sleep',cancel):
   with self.assertRaises(asyncio.CancelledError):await m.run_startup_trial(p,j,82,1,100)
  self.assertEqual(p.calls,[{'state':'ON','brightness':1,'transition':0}])
  self.assertEqual(j.result['startup_timings'][0]['phase'],'minimum_confirmed')
 async def test_changed_lamp_during_hold_prevents_restart(self):
  from unittest.mock import patch
  p=FakeProbe();j=Journal()
  async def changed(_):p.state.update(state='OFF',applied_output_on='OFF')
  with patch.object(m.asyncio,'sleep',changed):
   with self.assertRaisesRegex(RuntimeError,'minimo'):await m.run_startup_trial(p,j,82,1,100)
  self.assertEqual(len(p.calls),1)
 async def test_failed_minimum_does_not_start_wait_or_ramp(self):
  from unittest.mock import patch,AsyncMock
  p=FakeProbe();j=Journal();p.set=AsyncMock(side_effect=TimeoutError())
  with patch.object(m.asyncio,'sleep',new_callable=AsyncMock) as sleep:
   with self.assertRaises(TimeoutError):await m.run_startup_trial(p,j,82,1,1000)
   sleep.assert_not_awaited()
  self.assertEqual(p.set.await_count,1)
 async def test_protection_trip_during_hold_prevents_target(self):
  from unittest.mock import patch
  p=FakeProbe();j=Journal()
  async def trip(_):p.state.update(p031_output_blocked=True,p031_trip_count=1)
  with patch.object(m.asyncio,'sleep',trip):
   with self.assertRaisesRegex(RuntimeError,'P0.31'):await m.run_startup_trial(p,j,82,1,100)
  self.assertEqual(len(p.calls),1)
 async def test_full_series_is_operator_paced_and_keeps_configuration(self):
  from unittest.mock import patch,AsyncMock
  p=FakeProbe();j=Journal();before={k:p.state[k] for k in m.CONFIG}
  with patch.object(m,'enter',new_callable=AsyncMock) as enter,patch.object(m,'prompt',new_callable=AsyncMock,return_value='stabile'),patch.object(m.asyncio,'sleep',new_callable=AsyncMock):
   await m.startup_walkthrough(p,j,(100,300,1000),32.3)
  self.assertEqual(j.result['outcome'],'completed');self.assertEqual(len(j.result['startup_timings']),3)
  self.assertEqual([r['additional_hold_requested_ms'] for r in j.result['startup_timings']],[100,300,1000])
  self.assertEqual([c['brightness'] for c in p.calls if c.get('brightness') not in (None,1)],[82]*4)
  self.assertEqual(before,{k:p.state[k] for k in m.CONFIG});self.assertEqual(enter.await_count,8)
  self.assertTrue(all(set(c)<={'state','brightness','transition'} for c in p.calls))
 async def test_unhealthy_initial_protection_prevents_all_commands(self):
  p=FakeProbe();j=Journal();p.state['p031_sample_valid']=False
  with self.assertRaisesRegex(RuntimeError,'P0.31'):await m.startup_walkthrough(p,j,(100,),32.3)
  self.assertEqual(p.calls,[])

class StartupInputTests(unittest.TestCase):
 def test_incoming_abort_is_latched_after_healthy_report_returns(self):
  healthy=FakeProbe().state
  for kind,violation in [('protection',{'p031_sample_valid':False}),
    ('config',{'rise_transition_ms':500}),('output',{'state':'OFF','applied_output_on':'OFF'})]:
   with self.subTest(kind=kind):
    p=m.Probe('secret',10,Journal());p.expected_config={k:healthy[k] for k in m.CONFIG}
    p.expected_protection_trips=0;p.holding_minimum=1
    at_min={**healthy,'state':'ON','applied_output_on':'ON','applied_output_level':1}
    p.observe_state({**at_min,**violation});first_error=p.error
    self.assertIsInstance(first_error,RuntimeError)
    p.observe_state(at_min)
    self.assertIs(p.error,first_error)
 def test_finite_short_hold_list_only(self):
  import argparse
  self.assertEqual(m.parse_startup_holds('100,300,1000'),(100,300,1000))
  for value in ['','nan','100.5','-1','5001','100,,300']:
   with self.subTest(value=value):
    with self.assertRaises(argparse.ArgumentTypeError):m.parse_startup_holds(value)
