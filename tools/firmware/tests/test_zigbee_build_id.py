"""Exercise Basic SWBuildID initialization with the SDK's actual ZCL string macros."""
from local_inputs import local_input, sdk_root
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class BuildIdTests(unittest.TestCase):
    def test_zcl_build_id_contains_generated_version_and_rejects_oversize(self):
        source = (ROOT/'firmware/src/zigbee_device.c').read_text()
        initialize = re.search(r'ZB_ZCL_SET_STRING_VAL\(context.basic.sw_ver,.*?;', source, re.S)
        self.assertIsNotNone(initialize, 'Basic SWBuildID must expose the generated application version')
        bound = re.search(r'BUILD_ASSERT\(sizeof\(APP_VERSION_STRING\).*?;', source, re.S)
        self.assertIsNotNone(bound, 'a version must fit the 16-character Basic SWBuildID')
        sdk = local_input(sdk_root()/'ncs-zigbee/lib/zboss/include/zcl/zb_zcl_common.h').read_text()
        macros=[]
        for name in ['ZB_ZCL_SET_STRING_VAL','ZB_ZCL_STRING_CONST_SIZE']:
            lines=sdk[sdk.index('#define '+name+'('):].splitlines()
            definition=lines[0]
            index=1
            while definition.endswith('\\'):
                definition+='\n'+lines[index]
                index+=1
            macros.append(definition)
        for version, accepted in [('0.5.4-dev',True),('1234567890123456',True),('12345678901234567',False)]:
            program = '#include <stdint.h>\n#include <string.h>\n#include <assert.h>\ntypedef uint8_t zb_uint8_t;\n#define ZB_MEMCPY memcpy\n#define BUILD_ASSERT(cond,...) _Static_assert(cond,"version too long")\n'
            program += '\n'.join(macros)+'\n#define APP_VERSION_STRING "'+version+'"\n'
            program += 'static struct { struct { uint8_t sw_ver[17]; } basic; } context;\n'+bound.group(0)+'\nint main(void) {\n'+initialize.group(0)+'\n'
            program += 'assert(context.basic.sw_ver[0]=='+str(len(version))+');assert(memcmp(context.basic.sw_ver+1,"'+version+'",'+str(len(version))+')==0);return 0;}\n'
            with tempfile.TemporaryDirectory() as temporary:
                p=Path(temporary);(p/'test.c').write_text(program)
                result=subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(p/'test.c'),'-o',str(p/'test')],capture_output=True,text=True)
                if accepted:
                    self.assertEqual(result.returncode,0,result.stderr)
                    subprocess.run([str(p/'test')],check=True)
                else:
                    self.assertNotEqual(result.returncode,0)
                    self.assertIn('version too long',result.stderr)
