from pathlib import Path
import subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[3]
class VimarIdentityTests(unittest.TestCase):
 def test_preserves_stock_ieee_from_factory_ids(self):
  code='''#include <stdint.h>
#include <assert.h>
#include <string.h>
#include "vimar_identity.h"
int main(void){uint8_t address[8]; const uint8_t expected[]={0x88,0x77,0x66,0x55,0x44,0x36,0xce,0xf4};
vimar_identity(0x11223344,0x55667788,address);assert(memcmp(address,expected,8)==0);
vimar_identity(0x11223345,0x55667788,address);assert(address[4]==0x45);
return 0;}'''
  with tempfile.TemporaryDirectory() as tmp:
   source=Path(tmp)/'identity.c';source.write_text(code);exe=Path(tmp)/'identity'
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'firmware/src'),str(source),str(ROOT/'firmware/src/vimar_identity.c'),'-o',str(exe)],check=True)
   subprocess.run([str(exe)],check=True)
