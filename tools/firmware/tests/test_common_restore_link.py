"""Connection ownership/reconnect/drain admission used by the actual GATT adapter."""
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[3]

def test_real_link_policy_rejects_stale_completion_and_retains_old_worker_during_reconnect(tmp_path):
    source=ROOT/'firmware/common_restore/link.c'
    assert source.exists(),'Authenticated link ownership policy missing'
    test=tmp_path/'link.c'
    test.write_text('''#include "link.h"
#include <assert.h>
int main(void){struct common_restore_link s={0};
 unsigned a=common_restore_link_connect(&s);assert(a&&common_restore_link_needs_open(&s,false));
 common_restore_link_publish(&s,a);assert(common_restore_link_submit(&s,a,false));
 assert(common_restore_link_disconnect(&s,a));assert(s.busy);
 unsigned b=common_restore_link_connect(&s);assert(b&&b!=a);
 assert(!common_restore_link_needs_open(&s,false));assert(!common_restore_link_submit(&s,b,false));
 common_restore_link_publish(&s,a);assert(!s.published_owner);
 assert(common_restore_link_finish(&s,a));assert(common_restore_link_needs_open(&s,false));
 common_restore_link_publish(&s,b);assert(!common_restore_link_submit(&s,a,false));
 assert(!common_restore_link_submit(&s,b,true));assert(common_restore_link_submit(&s,b,false));
 assert(!common_restore_link_finish(&s,a)&&s.busy);assert(common_restore_link_finish(&s,b)&&!s.busy);
 assert(!common_restore_link_needs_open(&s,true));return 0;}''')
    exe=tmp_path/'link'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=undefined',
                    '-I'+str(source.parent),str(source),str(test),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
