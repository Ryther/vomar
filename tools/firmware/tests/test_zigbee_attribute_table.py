"""Exercise the actual compiled ZBOSS table, not only the codec's public IDs."""
from pathlib import Path
import re,subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[3]
class ZigbeeAttributeTableTests(unittest.TestCase):
 def test_every_public_attribute_is_readable_in_native_cluster(self):
  source=(ROOT/'firmware/src/zigbee_device.c').read_text();context=re.search(r'struct zigbee_context \{.*?\n\};',source,re.S).group(0)
  codec=(ROOT/'firmware/src/zigbee_custom_codec.h').read_text();enum=re.search(r'enum vimar_custom_attribute \{(.*?)\n\};',codec,re.S).group(1)
  ids=re.findall(r'\b(VIMAR_ATTR_[A-Z0-9_]+)\s*=',enum)
  with tempfile.TemporaryDirectory() as tmp:
   tmp=Path(tmp);(tmp/'zboss_api.h').write_text('''#include <stdint.h>
#include <stdbool.h>
typedef int zb_zcl_basic_attrs_ext_t;typedef int zb_zcl_identify_attrs_t;typedef int zb_zcl_scenes_attrs_t;typedef int zb_zcl_groups_attrs_t;typedef int zb_zcl_on_off_attrs_t;typedef int zb_zcl_level_control_attrs_t;typedef bool zb_bool_t;
typedef struct {uint16_t id;uint8_t type,access;uint16_t manufacturer;void *ptr;} zb_zcl_attr_t;
#define ZB_ZCL_ATTR_ACCESS_READ_ONLY 1
#define ZB_ZCL_ATTR_ACCESS_READ_WRITE 3
#define ZB_ZCL_NON_MANUFACTURER_SPECIFIC 0xffff
#define ZB_ZCL_ATTR_TYPE_BOOL 0x10
#define ZB_ZCL_ATTR_TYPE_U8 0x20
#define ZB_ZCL_ATTR_TYPE_U16 0x21
#define ZB_ZCL_ATTR_TYPE_U32 0x23
#define ZB_ZCL_ATTR_TYPE_CHAR_STRING 0x42
#define ZB_ZCL_ATTR_TYPE_OCTET_STRING 0x41
''')
   harness='''#include <assert.h>
#include <stdio.h>
#include "zb_vimar_custom.h"
'''+context+'''
static struct zigbee_context context;
ZB_DECLARE_VIMAR_CUSTOM_ATTR_LIST(attrs,&context);
static const uint16_t public_ids[]={'''+','.join(ids)+'''};
int main(void){
 for(unsigned i=0;i<sizeof(public_ids)/sizeof(public_ids[0]);i++){
  unsigned count=0;
  for(unsigned j=0;j<sizeof(attrs)/sizeof(attrs[0]);j++)if(attrs[j].id==public_ids[i]){
   count++;assert(attrs[j].ptr && (attrs[j].access&1));
   assert(attrs[j].manufacturer==0xffff);
   if(public_ids[i]>=0x500)assert(attrs[j].access==1);
  }
  if(count!=1){fprintf(stderr,"attribute0x%04x appears%u times in actual cluster table\\n",public_ids[i],count);return 1;}
 }
 return 0;
}
'''
   path=tmp/'table.c';path.write_text(harness);exe=tmp/'table'
   p=subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(tmp),'-I',str(ROOT/'firmware/src'),str(path),'-o',str(exe)],capture_output=True,text=True);self.assertEqual(p.returncode,0,p.stderr)
   p=subprocess.run([str(exe)],capture_output=True,text=True);self.assertEqual(p.returncode,0,p.stderr)
if __name__=='__main__':unittest.main()
