"""Migration rejects incompatible pending work and legacy ON before GPIO/copy."""
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[3]
def test_migration_policy_never_consumes_unsafe_authorization(tmp_path):
 c=tmp_path/'test.c';c.write_text(r'''
#include "migration_policy.h"
#include <errno.h>
#include <string.h>
#include <assert.h>
static uint8_t marker,record[20];static size_t len;static unsigned changes;
static int load(void*c,uint8_t*p,size_t n){(void)c;if(n!=len)return-EIO;memcpy(p,record,n);return 0;}
static int save(void*c,const uint8_t*p,size_t n){(void)c;memcpy(record,p,n);len=n;return 0;}
static int get(void*c,uint8_t*p){(void)c;*p=marker;return 0;}
static int set(void*c,uint8_t n){(void)c;marker=n;changes++;return 0;}
int main(void){
 struct research_handoff_io io={.load=load,.save=save,.get_marker=get,.set_marker=set};
 assert(!migration_protection_preflight(-ENOENT,&io));
 assert(!research_handoff_prepare(&io,123));unsigned before=changes;
 assert(migration_protection_preflight(0,&io)==-EPROTONOSUPPORT&&marker==0xa7&&changes==before);
 assert(migration_protection_preflight(176,&io)==-EBUSY&&changes==before);
 assert(!research_handoff_prepare(&io,-32768));assert(!migration_protection_preflight(0,&io)&&marker==0);
 struct research_protected_handoff h={.level=123,.armed=true};
 assert(!research_handoff_prepare_protected(&io,&h));before=changes;
 assert(!migration_protection_preflight(0,&io)&&marker==0xa8&&changes==before);
 record[19]^=1;assert(migration_protection_preflight(0,&io)<0&&changes==before);
 assert(migration_protection_preflight(-EIO,&io)==-EIO);return 0;
}
''')
 out=tmp_path/'policy';subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'firmware/ota_migration/src'),'-I',str(ROOT/'firmware/research/src'),str(c),str(ROOT/'firmware/ota_migration/src/migration_policy.c'),str(ROOT/'firmware/research/src/research_handoff.c'),'-o',str(out)],check=True);subprocess.run([str(out)],check=True)
