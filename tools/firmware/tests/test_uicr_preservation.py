import importlib.util
from pathlib import Path
import unittest
path=Path(__file__).resolve().parents[1]/'validate_recovery.py'
spec=importlib.util.spec_from_file_location('validation',path);v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
class UicrPreservationTests(unittest.TestCase):
 def test_rejects_runtime_debugctrl_writer_in_any_image(self):
  for image in ('main','mcuboot','recovery','restorer','bootstrap'):
   with self.subTest(image=image),self.assertRaisesRegex(ValueError,'DISABLE_FLASH_PATCH'):
    v.validate_uicr_preservation({image:{'CONFIG_DISABLE_FLASH_PATCH':'y'}},{})
 def test_rejects_conditional_nrf_startup_writers(self):
  for macro in ('NRF_CONFIG_GPIO_AS_PINRESET','NRF_CONFIG_NFCT_PINS_AS_GPIOS','CONFIG_GPIO_AS_PINRESET','CONFIG_NFCT_PINS_AS_GPIOS'):
   with self.subTest(macro=macro),self.assertRaisesRegex(ValueError,macro):
    v.validate_uicr_preservation({'main':{}},{'main':{macro}})
 def test_accepts_profile_without_automatic_writers(self):
  v.validate_uicr_preservation({'main':{'CONFIG_DISABLE_FLASH_PATCH':'n','CONFIG_NRF_APPROTECT_USE_UICR':'y'}},{'main':{'NRF52840_XXAA'}})
