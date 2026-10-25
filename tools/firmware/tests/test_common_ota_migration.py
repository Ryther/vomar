"""Common migration preparation uses only public signatures and finite loader authority."""
from local_inputs import local_input
import hashlib
import json
import struct
import subprocess
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

ROOT = Path(__file__).resolve().parents[3]


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def common_source(tmp_path, monkeypatch):
    from tools.firmware import build_common_ota_migration as builder
    # Ephemeral test identity; never load the repository's firmware private key.
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.DER,
                                         serialization.PublicFormat.SubjectPublicKeyInfo)
    public_path = tmp_path / 'test-public.pem'
    public_path.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
                                                        serialization.PublicFormat.SubjectPublicKeyInfo))
    monkeypatch.setattr(builder, 'PUBLIC_KEY', public_path)
    # Only the tests reaching the real external SDK verification need imgtool.
    # Earlier manifest/geometry rejections remain active without an SDK.
    from tools.firmware import package_zigbee_ota as package
    verify_with_imgtool = builder.run_imgtool
    def optional_sdk_verification(arguments, commands):
        local_input(package.PYTHON)
        local_input(package.IMGTOOL)
        return verify_with_imgtool(arguments, commands)
    monkeypatch.setattr(builder, 'run_imgtool', optional_sdk_verification)

    def signed_recovery(role=b'\x02', target=b'VIMAR30805\x02'):
        def tlv(tag, value):
            return struct.pack('<HH', tag, len(value)) + value
        payload = struct.pack('<II', 0x20010000, 0xb0201) + bytes(56)
        entries = tlv(0xa0, target) + tlv(0xa1, role)
        protected = struct.pack('<HH', 0x6908, len(entries) + 4) + entries
        header = struct.pack('<IIHHII', 0x96f3b83d, 0, 512, len(protected), len(payload), 0)
        header += struct.pack('<BBHI', 0, 9, 0, 0) + bytes(4)
        signed = header + bytes(512-len(header)) + payload + protected
        signature = key.sign(signed, ec.ECDSA(hashes.SHA256()))
        ordinary = tlv(0x10, hashlib.sha256(signed).digest())
        ordinary += tlv(1, hashlib.sha256(public).digest()) + tlv(0x22, signature)
        return signed + struct.pack('<HH', 0x6907, len(ordinary) + 4) + ordinary

    def record(name, data):
        path = tmp_path / name
        path.write_bytes(data)
        return dict(path=path.name, sha256=sha(data))

    loader = record('loader.raw.bin', bytes(0xc000))
    loader_config = record('loader.config', b'CONFIG_BOOT_FIRMWARE_LOADER=y\nCONFIG_BOOT_VALIDATE_SLOT0=y\nCONFIG_BOOT_SIGNATURE_TYPE_ECDSA_P256=y\n')
    recovery_config = record('recovery.config', b'CONFIG_VIMAR_OTA_SPLIT_STAGING=y\nCONFIG_VIMAR_P031_PROTECTION=y\nCONFIG_VIMAR_OTA_INSTALLER=y\nCONFIG_NRF_COMPRESS_LZMA_MAX_DICT_SIZE=32768\nCONFIG_DISABLE_FLASH_PATCH=n\n')
    registry = dict(schema_version=1, ota_profile=2, allowed_loaders=[loader['sha256']],
                    reference_loader_config_sha256=loader_config['sha256'])
    manifest = dict(schema_version=1, kind='common-recovery-migration', model='VIMAR30805',
                    ota_profile=2, recovery_signed=record('recovery.bin', signed_recovery()),
                    recovery_config=recovery_config, audited_loader_config=loader_config,
                    loader_compatibility_registry=record('registry.json', json.dumps(registry).encode()),
                    allowed_loaders=[loader])
    manifest_path = tmp_path / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest))
    return builder, manifest_path, manifest, record, signed_recovery


def test_prepare_freezes_common_headers_without_uid_restorer_or_signing(common_source, tmp_path):
    builder, path, manifest, _, _ = common_source
    first = builder.prepare_common_migration(path, tmp_path / 'first')
    second = builder.prepare_common_migration(path, tmp_path / 'second')
    assert 'generated_dir' in first
    generated = Path(first['generated_dir'])
    other = Path(second['generated_dir'])
    assert sorted(p.name for p in generated.iterdir()) == ['common_platform.h', 'recovery_blob.h']
    assert {p.name: p.read_bytes() for p in generated.iterdir()} == {p.name: p.read_bytes() for p in other.iterdir()}
    header = (generated / 'common_platform.h').read_text()
    assert 'MIGRATION_UID' not in header and 'restorer' not in header
    report = json.loads(Path(first['manifest_path']).read_text())
    assert report['allowed_loaders'] == [manifest['allowed_loaders'][0]['sha256']]
    assert report['hardware_qualified'] is False
    assert report['recovery_role'] == 'recovery' and report['ota_profile'] == 2
    assert all('sign' not in command[2:3] for command in report['commands'])
    assert not list((tmp_path/'first').rglob('*.pem'))


@pytest.mark.parametrize('damage', ['loader_hash', 'loader_size', 'unknown_loader', 'registry_config',
    'registry_hash', 'missing_loader', 'too_many_loaders', 'bad_loader_config', 'bad_recovery_config',
    'wrong_role', 'missing_role', 'wrong_profile', 'tampered_signature', 'recovery_hash', 'per_unit_uid',
    'invalid_registry', 'duplicate_loader'])
def test_rejects_unqualified_common_inputs_before_creating_output(common_source, tmp_path, damage):
    builder, path, manifest, record, recovery = common_source
    if damage == 'loader_hash': manifest['allowed_loaders'][0]['sha256'] = '00'*32
    if damage == 'loader_size': manifest['allowed_loaders'] = [record('short.bin', bytes(0xbfff))]
    if damage == 'unknown_loader':
        registry = dict(schema_version=1, ota_profile=2, allowed_loaders=['11'*32],
            reference_loader_config_sha256=manifest['audited_loader_config']['sha256'])
        manifest['loader_compatibility_registry'] = record('registry.json', json.dumps(registry).encode())
    if damage == 'registry_config':
        registry = json.loads((tmp_path/'registry.json').read_text())
        registry['reference_loader_config_sha256'] = '00'*32
        manifest['loader_compatibility_registry'] = record('registry.json', json.dumps(registry).encode())
    if damage == 'registry_hash': manifest['loader_compatibility_registry']['sha256'] = '00'*32
    if damage == 'missing_loader': manifest['allowed_loaders'] = []
    if damage == 'too_many_loaders': manifest['allowed_loaders'] *= 65
    if damage == 'bad_loader_config': manifest['audited_loader_config'] = record('bad.config', b'CONFIG_BOOT_FIRMWARE_LOADER=n\n')
    if damage == 'bad_recovery_config': manifest['recovery_config'] = record('bad.config', b'CONFIG_DISABLE_FLASH_PATCH=y\n')
    if damage == 'wrong_role': manifest['recovery_signed'] = record('recovery.bin', recovery(role=b'\x01'))
    if damage == 'missing_role': manifest['recovery_signed'] = record('recovery.bin', recovery(role=b''))
    if damage == 'wrong_profile': manifest['recovery_signed'] = record('recovery.bin', recovery(target=b'VIMAR30805\x01'))
    if damage == 'tampered_signature':
        blob = (tmp_path/'recovery.bin').read_bytes()
        manifest['recovery_signed'] = record('recovery.bin', blob[:-1] + bytes([blob[-1]^1]))
    if damage == 'recovery_hash': manifest['recovery_signed']['sha256'] = '00'*32
    if damage == 'per_unit_uid': manifest['uid'] = ['12345678', 'abcdef01']
    if damage == 'invalid_registry': manifest['loader_compatibility_registry'] = record('registry.json', b'[]')
    if damage == 'duplicate_loader': manifest['allowed_loaders'] *= 2
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError): builder.prepare_common_migration(path, tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_common_guards_use_same_header_for_two_runtime_uids(common_source, tmp_path):
    builder, manifest_path, _, _, _ = common_source
    result = builder.prepare_common_migration(manifest_path, tmp_path/'out')
    assert 'generated_dir' in result
    source = tmp_path/'guards.c'
    source.write_text(r'''
#include "common_platform.h"
#include "recovery_blob.h"
#include "migration_copy.h"
#include "ota_image.h"
#include <assert.h>
#include <errno.h>
#include <string.h>
#include <openssl/sha.h>
static uint8_t memory[0x100000];
static uint32_t current_uid[2];
static unsigned mutations;
static struct ota_image_info verified;
static int uid(void*c,uint32_t out[2]){(void)c;memcpy(out,current_uid,8);return 0;}
static int hash(void*c,const uint8_t*p,size_t n,uint8_t out[32]){(void)c;SHA256(p,n,out);return 0;}
/* Signature verification is exercised by preparation with a real ephemeral
 * key; this copy-policy boundary supplies authenticated metadata explicitly. */
static int verify(void*c,const uint8_t*p,size_t n){(void)c;(void)p;return migration_common_recovery_authorized(&verified,n);}
static int read_mem(void*c,uint32_t a,uint8_t*p,size_t n){(void)c;assert(a>=0xb0000&&a<=0xf0000-n);memcpy(p,memory+a,n);return 0;}
static int erase(void*c,uint32_t a,size_t n){(void)c;assert(a>=0xb0000&&a<=0xf0000-n&&n==4096);mutations++;memset(memory+a,255,n);return 0;}
static int write_mem(void*c,uint32_t a,const uint8_t*p,size_t n){(void)c;assert(a>=0xb0000&&a<=0xf0000-n&&n==4096);mutations++;memcpy(memory+a,p,n);return 0;}
int main(void) {
 uint8_t actual[32]; memcpy(actual,migration_allowed_loaders[0],32);
 assert(!migration_common_loader_authorized(actual,migration_allowed_loaders,MIGRATION_ALLOWED_LOADER_COUNT));
 actual[0]^=1;
 assert(migration_common_loader_authorized(actual,migration_allowed_loaders,MIGRATION_ALLOWED_LOADER_COUNT)==-EACCES);
 assert(migration_common_loader_authorized(actual,migration_allowed_loaders,0)<0);
 struct ota_image_info info={.output_size=700,.authenticated_role=OTA_IMAGE_ROLE_RECOVERY,.authenticated_profile=2};
 assert(!migration_common_recovery_authorized(&info,700));
 info.authenticated_role=OTA_IMAGE_ROLE_MAIN;assert(migration_common_recovery_authorized(&info,700)<0);
 info.authenticated_role=OTA_IMAGE_ROLE_RECOVERY;info.authenticated_profile=1;
 assert(migration_common_recovery_authorized(&info,700)<0);
 info.authenticated_profile=2;assert(migration_common_recovery_authorized(&info,701)<0);
 info.output_size=0x34001;assert(migration_common_recovery_authorized(&info,0x34001)<0);
 const uint32_t runtime_uids[2][2]={{0x12345678,0xabcdef01},{0xfedcba98,0x76543210}};
 const struct migration_copy_io io={.read_uid=uid,.sha256=hash,.verify_image=verify,.read=read_mem,.erase=erase,.write=write_mem};
 for(unsigned i=0;i<2;i++) {
  memcpy(current_uid,runtime_uids[i],8);memset(memory,0xa5,sizeof(memory));mutations=0;
  struct migration_copy_bundle bundle={.uid={current_uid[0],current_uid[1]},.data=recovery_blob,.size=RECOVERY_BLOB_SIZE};
  memcpy(bundle.sha256,expected_recovery_sha256,32);
  verified=(struct ota_image_info){.output_size=RECOVERY_BLOB_SIZE,.authenticated_role=OTA_IMAGE_ROLE_RECOVERY,.authenticated_profile=2};
  assert(!migration_copy_run(&bundle,&io));assert(mutations==128);
  assert(!memcmp(memory+0xb0000,recovery_blob,RECOVERY_BLOB_SIZE));
  for(size_t a=0;a<0xb0000;a++)assert(memory[a]==0xa5);
  for(size_t a=0xb0000+RECOVERY_BLOB_SIZE;a<0xf0000;a++)assert(memory[a]==255);
  for(size_t a=0xf0000;a<sizeof(memory);a++)assert(memory[a]==0xa5);
  mutations=0;assert(!migration_copy_run(&bundle,&io));assert(!mutations);
  current_uid[0]^=1;assert(migration_copy_run(&bundle,&io)==-EACCES);assert(!mutations);
  current_uid[0]^=1;verified.authenticated_role=OTA_IMAGE_ROLE_MAIN;
  assert(migration_copy_run(&bundle,&io)==-EACCES);assert(!mutations);
 }
 return 0;
}''')
    binary = tmp_path/'guards'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I'+result['generated_dir'],
        '-I'+str(ROOT/'firmware/ota_migration/src'),'-I'+str(ROOT/'firmware/ota'),str(source),
        str(ROOT/'firmware/ota_migration/src/migration_copy.c'),'-lcrypto','-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)


def test_unsigned_command_never_uses_private_key_or_signs(common_source, tmp_path):
    builder, manifest_path, _, _, _ = common_source
    result = builder.prepare_common_migration(manifest_path, tmp_path/'out')
    assert 'generated_dir' in result
    command = builder.unsigned_build_command(result)
    assert '-DCONFIG_MIGRATION_COMMON=y' in command
    assert '-DCONFIG_MCUBOOT_GENERATE_UNSIGNED_IMAGE=n' in command
    assert '-DCONFIG_MCUBOOT_SIGNATURE_KEY_FILE=""' in command
    index = command.index('--target')
    assert command[index+1] == 'zephyr/zephyr.elf' and index < command.index('--')
