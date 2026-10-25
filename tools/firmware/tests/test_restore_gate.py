from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[3]
class RestoreGateTests(unittest.TestCase):
    def test_only_verified_exact_restorer_in_scratch_is_authorized(self):
        with tempfile.TemporaryDirectory() as directory:
            exe = str(Path(directory) / 'gate-test')
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                '-I', str(ROOT / 'firmware/restore_gate'),
                str(ROOT / 'firmware/restore_gate/restore_policy.c'),
                str(Path(__file__).with_name('restore_gate_test.c')), '-o', exe], check=True)
            subprocess.run([exe], check=True)

    def test_adapter_keeps_protection_on_failed_signature_hash_and_normal_boot(self):
        # Compile the real adapter with host stand-ins for MCUboot/Zephyr only.
        headers = {
            'zephyr/kernel.h': '#include <stddef.h>\n',
            'bootutil/bootutil.h': '#include <stdint.h>\n#include <stddef.h>\ntypedef int fih_ret;\nstruct boot_rsp { const void *br_hdr; uint8_t br_flash_dev_id; uint32_t br_image_off; };\n',
            'bootutil/fault_injection_hardening.h': '#define FIH_FAILURE -1\n#define FIH_SUCCESS 0\n#define FIH_DECLARE(n,v) int n=v\n#define FIH_CALL(f,r,...) r=f(__VA_ARGS__)\n#define FIH_EQ(a,b) ((a)==(b))\n#define FIH_RET(r) return r\n',
            'bootutil/crypto/sha.h': '#define IMAGE_HASH_SIZE 32\n#include <stdint.h>\ntypedef int bootutil_sha_context;\nint bootutil_sha_init(int*);\nint bootutil_sha_update(int*, const void*, uint32_t);\nint bootutil_sha_finish(int*,uint8_t*);\nint bootutil_sha_drop(int*);\n',
            'fprotect.h': '#include <stddef.h>\n#include <stdint.h>\nint fprotect_area(uint32_t,size_t);\n',
            'restorer_hash.h': 'static const unsigned char authorized_restorer_hash[32]={1};\n',
        }
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for name, content in headers.items():
                file = base / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(content)
            exe = str(base / 'adapter-test')
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                '-DCONFIG_VIMAR_STOCK_RESTORER_SIZE=185803', '-I', directory,
                '-I', str(ROOT / 'firmware/restore_gate'),
                str(ROOT / 'firmware/restore_gate/restore_gate.c'),
                str(ROOT / 'firmware/restore_gate/restore_policy.c'),
                str(Path(__file__).with_name('restore_gate_adapter_test.c')), '-o', exe], check=True)
            subprocess.run([exe], check=True)
            sha = base / 'bootutil/crypto/sha.h'
            sha.write_text(sha.read_text().replace('IMAGE_HASH_SIZE 32', 'IMAGE_HASH_SIZE 64'))
            rejected = subprocess.run(['cc', '-std=c11',
                '-DCONFIG_VIMAR_STOCK_RESTORER_SIZE=185803', '-I', directory,
                '-I', str(ROOT / 'firmware/restore_gate'), '-c',
                str(ROOT / 'firmware/restore_gate/restore_gate.c'),
                '-o', str(base / 'unsupported.o')], capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn('Restorer allowlist requires SHA-256', rejected.stderr)
