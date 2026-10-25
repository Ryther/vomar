"""Exercise actual transport callbacks and deferred worker with host platform IO."""
from local_inputs import local_input, sdk_root
from pathlib import Path
import subprocess
import pytest
ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize('profile',[1,2,3])
def test_zigbee_ota_transport(tmp_path,profile):
    binary = tmp_path / 'zigbee_ota'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=undefined', *(['-DCONFIG_VIMAR_LOADER_RUNTIME_V2=1'] if profile==3 else []), *(['-DCONFIG_MAIN_STACK_SIZE=12288' if profile==3 else '-DCONFIG_MAIN_STACK_SIZE=8192','-DCONFIG_VIMAR_OTA_SPLIT_STAGING=1','-DVIMAR_OTA_PAIR_BINDINGS_HEADER="pair_bindings.h"'] if profile>=2 else []), '-I', str(ROOT / 'tools/firmware/tests/ota_transport_stubs'),
                    '-I', str(ROOT / 'firmware/ota'), '-I', str(ROOT / 'firmware/src'), '-I',str(ROOT/'firmware/loader_contract'),
                    str(ROOT / 'tools/firmware/tests/ota_transport_stubs/transport_test.c'),
                    *[str(ROOT / 'firmware/ota' / name) for name in
                      ['ota_stage.c', 'ota_format.c', 'ota_transaction.c','ota_split_stage.c']],
                    '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)


def test_split_ota_rejects_undersized_startup_crypto_stack(tmp_path):
    result=subprocess.run(['cc','-std=c11','-DCONFIG_MAIN_STACK_SIZE=2048',
        '-DCONFIG_VIMAR_OTA_SPLIT_STAGING=1','-DVIMAR_OTA_PAIR_BINDINGS_HEADER="pair_bindings.h"',
        '-I',str(ROOT/'tools/firmware/tests/ota_transport_stubs'),
        '-I',str(ROOT/'firmware/ota'),'-I',str(ROOT/'firmware/src'),
        '-c',str(ROOT/'tools/firmware/tests/ota_transport_stubs/transport_test.c'),
        '-o',str(tmp_path/'undersized.o')],capture_output=True,text=True)
    assert result.returncode != 0, 'Split startup signature verification must not run on the overflowing2KiB main stack'
    assert 'static assertion failed' in result.stderr


def test_actual_project_recovery_signed_region_digest_is_smp_hash_not_file_hash(tmp_path):
    import ctypes,hashlib,json,struct
    from test_image_roles import Info
    library=tmp_path/'actual_digest.so'
    subprocess.run(['cc','-shared','-fPIC','-std=c11','-Wno-deprecated-declarations',
        '-DOTA_IMAGE_AUTH_ONLY','-DOTA_IMAGE_HOST','-I'+str(ROOT/'firmware/ota'),
        str(ROOT/'firmware/ota/ota_image.c'),'-lcrypto','-o',str(library)],check=True)
    verify=ctypes.CDLL(str(library)).ota_image_verify_primary_for_profile
    verify.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint,ctypes.POINTER(Info)]
    candidate=ROOT/'experiments/common-candidate-0.6.0-20261023'
    manifest=json.loads(local_input(candidate/'candidate-manifest.json').read_text())
    blob=(candidate/'artifacts/recovery-0.8.0.signed.bin').read_bytes();info=Info()
    assert verify(blob,len(blob),2,ctypes.byref(info))==0
    assert info.authenticated_role==2 and info.authenticated_profile==2
    end=512+struct.unpack_from('<I',blob,12)[0]+struct.unpack_from('<H',blob,10)[0]
    signed=hashlib.sha256(blob[:end]).digest();full=hashlib.sha256(blob).digest()
    assert signed!=full and bytes(info.signed_digest)==signed and bytes(info.output_digest)==full
    assert signed.hex()==manifest['artifacts']['recovery']['signed_region_sha256']
    assert full.hex()==manifest['artifacts']['recovery']['sha256']
    offset=end+4;digests=[]
    while offset<len(blob):
        tag,length=struct.unpack_from('<HH',blob,offset);offset+=4
        if tag==0x10:digests.append(blob[offset:offset+length])
        offset+=length
    assert digests==[signed]
