from pathlib import Path
import importlib.util,struct,tempfile,unittest
ROOT=Path(__file__).resolve().parents[3]
class QualificationTests(unittest.TestCase):
 def module(self):
  spec=importlib.util.spec_from_file_location('qualify',ROOT/'tools/firmware/qualify_zigbee_ota.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
 def test_upload_targets_exact_ieee_and_validated_container(self):
  m=self.module();data=bytearray(70);struct.pack_into('<IHHHHHIH',data,0,0x0beef11e,0x100,60,4,0xfff1,0x3085,0x50300,2);struct.pack_into('<IHHHI',data,52,70,1,1,0,4)
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'test.ota';p.write_bytes(data);v=m.prepare_update('0x0011223344556677',p)
   self.assertEqual(v['id'],'0x0011223344556677');self.assertEqual(bytes.fromhex(v['hex']['data']),data)
   with self.assertRaises(ValueError):m.prepare_update('Bagno',p)
   data[10]=0;p.write_bytes(data)
   with self.assertRaises(ValueError):m.prepare_update('0x0011223344556677',p)
 def test_response_correlates_transaction_and_unrelated_progress_ignored(self):
  m=self.module()
  self.assertIsNone(m.correlated_result({'topic':'bridge/response/device/ota_update/update','payload':{'transaction':'other','status':'ok'}},'wanted'))
  self.assertEqual(m.correlated_result({'topic':'bridge/response/device/ota_update/update','payload':{'transaction':'wanted','status':'error','error':'failed'}},'wanted')['error'],'failed')

 def test_explicit_small_block_preserves_exact_image_and_target(self):
  m=self.module();data=bytearray(70);struct.pack_into('<IHHHHHIH',data,0,0x0beef11e,0x100,60,4,0xfff1,0x3085,0x50400,2);struct.pack_into('<IHHHI',data,52,70,1,1,0,4)
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'test.ota';p.write_bytes(data)
   self.assertEqual(m.prepare_update('0x0011223344556677',p)['default_maximum_data_size'],64)
   v=m.prepare_update('0x0011223344556677',p,48)
   self.assertEqual(v['default_maximum_data_size'],48)
   self.assertEqual(bytes.fromhex(v['hex']['data']),data)
   for size in [0,65,47,True]:
    with self.subTest(size=size),self.assertRaises(ValueError):m.prepare_update('0x0011223344556677',p,size)
