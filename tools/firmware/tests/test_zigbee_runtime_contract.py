"""Run the actual serialized producer body without radio/storage platform IO."""
from pathlib import Path
import re,subprocess
ROOT=Path(__file__).resolve().parents[3]

def test_scheduler_producer_advances_in_ram_and_preserves_atomic_read_snapshot(tmp_path):
    source=(ROOT/'firmware/src/zigbee_device.c').read_text()
    body=re.search(r'static void refresh_ota_contract\(uint64_t now_ms,bool force\)\n\{.*?\n\}',source,re.S).group(0)
    harness=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include "ota_runtime_contract.h"
#define CONFIG_VIMAR_ZIGBEE_OTA 1
static struct {uint32_t boot_sequence;uint8_t ota_contract[OTA_RUNTIME_CONTRACT_ZCL_SIZE];} context;
static uint32_t ota_contract_sample;static uint64_t ota_contract_updated_ms;
static bool verified;static unsigned reads;
static bool zigbee_ota_recovery_snapshot(uint8_t digest[32]){reads++;memset(digest,verified?0xa5:0,32);return verified;}
'''+body+r'''
int main(void){
 context.boot_sequence=123;
 refresh_ota_contract(0,true);assert(ota_contract_sample==1&&reads==1&&context.ota_contract[0]==43);
 uint8_t original[44];memcpy(original,context.ota_contract,44);
 refresh_ota_contract(999,false);assert(reads==1&&!memcmp(original,context.ota_contract,44));
 refresh_ota_contract(1000,false);assert(ota_contract_sample==2&&reads==2&&memcmp(original,context.ota_contract,44));
 verified=true;refresh_ota_contract(2000,false);assert(ota_contract_sample==3&&reads==3);
 uint8_t expected[44],digest[32];memset(digest,0xa5,32);
 assert(!ota_runtime_contract_encode(3,123,true,digest,expected));assert(!memcmp(expected,context.ota_contract,44));
 ota_contract_sample=UINT32_MAX;refresh_ota_contract(3000,false);assert(ota_contract_sample==0);
 assert(!ota_runtime_contract_encode(0,123,true,digest,expected));assert(!memcmp(expected,context.ota_contract,44));
 return 0;
}
'''
    path=tmp_path/'producer.c';path.write_text(harness);exe=tmp_path/'producer'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=undefined','-fno-sanitize-recover=all',
        '-I',str(ROOT/'firmware/src'),str(path),str(ROOT/'firmware/src/ota_runtime_contract.c'),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
