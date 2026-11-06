"""Execute the production snapshot code with synthetic counters, without radio IO."""
from pathlib import Path
import re,subprocess
import pytest
ROOT=Path(__file__).resolve().parents[3]

@pytest.mark.parametrize('enabled',[False,True])
def test_application_heartbeat_and_guard_counters_are_read_only_snapshots(tmp_path,enabled):
    source=(ROOT/'firmware/src/zigbee_device.c').read_text()
    match=re.search(r'static void refresh_ownership_diagnostics\(void\)\n\{.*?\n\}',source,re.S)
    assert match,'Application must expose the actual ownership snapshot'
    harness='''#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
static struct {bool ownership_guard_enabled;uint32_t application_ticks,ownership_local_requests,ownership_confirmations,ownership_restored_confirmations,ownership_storage_errors;} context;
volatile uint32_t vimar_ownership_local_requests=17,vimar_ownership_confirmations=31,vimar_ownership_restored_confirmations=2,vimar_ownership_storage_errors=4;
'''+match[0]+'''
int main(void){refresh_ownership_diagnostics();assert(context.application_ticks==1);
#if defined(CONFIG_VIMAR_ZIGBEE_OWNERSHIP_GUARD)
assert(context.ownership_guard_enabled);assert(context.ownership_local_requests==17);assert(context.ownership_confirmations==31);assert(context.ownership_restored_confirmations==2);assert(context.ownership_storage_errors==4);
#else
assert(!context.ownership_guard_enabled);assert(!context.ownership_local_requests);assert(!context.ownership_confirmations);assert(!context.ownership_restored_confirmations);assert(!context.ownership_storage_errors);
#endif
context.application_ticks=UINT32_MAX;refresh_ownership_diagnostics();assert(!context.application_ticks);
assert(vimar_ownership_local_requests==17 && vimar_ownership_confirmations==31 && vimar_ownership_restored_confirmations==2 && vimar_ownership_storage_errors==4);
return 0;}
'''
    c=tmp_path/'snapshot.c';c.write_text(harness);exe=tmp_path/'snapshot'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',*(['-DCONFIG_VIMAR_ZIGBEE_OWNERSHIP_GUARD=1'] if enabled else []),str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
    tick=re.search(r'static void application_tick\([^;]*?\)\n\{.*?\n\}',source,re.S)[0]
    assert 'refresh_ownership_diagnostics();' in tick
