from local_inputs import local_input, sdk_root
from pathlib import Path
import subprocess
import cbor2

ROOT = Path(__file__).resolve().parents[3]
ZCBOR = sdk_root()/"modules/lib/zcbor"


def test_identity_uses_live_uid_and_bounded_cbor_without_a_device_manifest(tmp_path):
    source = tmp_path / "identity.c"
    source.write_text(r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include "recovery_identity.h"
int main(int argc,char **argv) {
 unsigned char output[256], hash[32];
 for(unsigned i=0;i<32;i++)hash[i]=(unsigned char)i;
 uint32_t uid[]={argc>1?(uint32_t)strtoul(argv[1],NULL,10):0,4294967295u};
 ZCBOR_STATE_E(state,4,output,sizeof(output),1);
 assert(zcbor_map_start_encode(state,5));
 assert(recovery_identity_encode(state,uid,hash));
 assert(zcbor_map_end_encode(state,5));
 fwrite(output,1,(size_t)(state->payload-output),stdout);
 unsigned char tiny[2];
 ZCBOR_STATE_E(small,4,tiny,sizeof(tiny),1);
 assert(!recovery_identity_encode(small,uid,hash));
 return 0;
}
''')
    exe = tmp_path / "identity"
    local_input(ZCBOR)
    subprocess.run([
        "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-DZCBOR_CANONICAL",
        "-I", str(ZCBOR / "include"), "-I", str(ROOT / "firmware/recovery/src"),
        str(source), str(ROOT / "firmware/recovery/src/recovery_identity.c"),
        str(ZCBOR / "src/zcbor_common.c"), str(ZCBOR / "src/zcbor_encode.c"), "-o", str(exe),
    ], check=True)
    for uid in (1, 0x11223344):
        data = subprocess.check_output([str(exe), str(uid)])
        assert cbor2.loads(data) == {"protocol": 1, "model": "VIMAR30805", "layout": 2,
                                   "uid": [uid, 0xFFFFFFFF], "loader_sha256": bytes(range(32))}
        assert len(data) < 200
