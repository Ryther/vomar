#!/usr/bin/env python3
"""Prepare private Zigbee releases; never communicates with physical devices.

Manifest schema 1 pins current_signed, candidate_signed and candidate_unsigned
as {path, sha256}; paths resolve relative to the manifest. Required identity:
manufacturer_code=65521, image_type=12421, hardware_min=hardware_max=1.
New versions use major.minor.patch; historical major.minor.patch+build inputs
remain readable. Zigbee wire fields must each fit a byte; new releases have
build zero. SDK/key paths are repository-local.
The staging writer strips the fixed 66-byte OTA envelope and stages its sole
compressed signed-image subelement. No XZ container or default slot1 is used.
"""
import argparse
import hashlib
import json
import lzma
from pathlib import Path
import re
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.firmware.toolchain_paths import toolchain_paths
_TOOLCHAIN = toolchain_paths()
SDK = _TOOLCHAIN['sdk'] / 'bootloader/mcuboot'
PYTHON = _TOOLCHAIN['python']
IMGTOOL = _TOOLCHAIN['imgtool']
ENCODER_ADAPTER = ROOT / 'tools/firmware/imgtool_bt2_adapter.py'
PUBLIC_KEY = _TOOLCHAIN['public_key']
PRIVATE_KEY = _TOOLCHAIN['private_key']
MANUFACTURER_CODE = 0xfff1
IMAGE_TYPE = 0x3085
HARDWARE_VERSION = 1
TARGET_TLV = 0xa0
TARGET_VALUE = b'VIMAR30805\x01'
IMAGE_ROLE_TLV = 0xa1
IMAGE_ROLES = dict(main=1, recovery=2, migration=3, restore=4, diagnostic=5)
PRIMARY_START = 0xc000
PRIMARY_END = 0xb0000
STAGE_END = 0xae000
PAGE = 4096


def sha(data):
    return hashlib.sha256(data).hexdigest()


def version_tuple(version):
    """Read public triples and historical MCUboot labels without losing build."""
    match = re.fullmatch(r'([0-9]+)\.([0-9]+)\.([0-9]+)(?:\+([0-9]+))?', version) if isinstance(version, str) else None
    if not match:
        raise ValueError('version must be major.minor.patch or historical major.minor.patch+build')
    numbers = tuple(int(n) if n is not None else 0 for n in match.groups())
    if any(n > limit for n, limit in zip(numbers, (255, 255, 65535, 0xffffffff))):
        raise ValueError('version exceeds MCUboot field widths')
    return numbers


def ota_version(version):
    # dfu_multi_target.c union: little endian build, revision, minor, major.
    major, minor, revision, build = version_tuple(version)
    if any(n > 255 for n in (major, minor, revision, build)):
        raise ValueError('Zigbee version requires byte fields')
    return major << 24 | minor << 16 | revision << 8 | build


def stage_budget(current_size, compressed_size, destination_size):
    if any(type(n) is not int or n <= 0 or n > 0xffffffff
           for n in (current_size, compressed_size, destination_size)):
        raise ValueError('invalid image sizes')
    current_end = PRIMARY_START + current_size
    destination_end = PRIMARY_START + destination_size
    if (current_end > STAGE_END or destination_end > STAGE_END or
            compressed_size > STAGE_END - PRIMARY_START):
        raise ValueError('image exceeds bounded primary area')
    start = (STAGE_END - compressed_size) // PAGE * PAGE
    current_erase_end = (current_end + PAGE - 1) // PAGE * PAGE
    destination_erase_end = (destination_end + PAGE - 1) // PAGE * PAGE
    if max(current_erase_end, destination_erase_end) > start:
        raise ValueError('stage overlaps current or reconstructed image erase interval')
    return dict(stage_start=start, stage_end=STAGE_END,
                compressed_size=compressed_size, current_end=current_end,
                current_erase_end=current_erase_end, destination_end=destination_end,
                destination_erase_end=destination_erase_end,
                free_bytes=start-max(current_erase_end, destination_erase_end))


def split_stage_budget(current_size,compressed_size,destination_size,recovery_size):
    if any(type(n) is not int or n<=0 or n>0xffffffff for n in (current_size,compressed_size,destination_size,recovery_size)):
        raise ValueError('invalid split image sizes')
    if recovery_size>0x34000:
        raise ValueError('recovery collides with protected staging tail')
    current_end,destination_end=PRIMARY_START+current_size,PRIMARY_START+destination_size
    current_erase_end=(current_end+PAGE-1)//PAGE*PAGE
    destination_erase_end=(destination_end+PAGE-1)//PAGE*PAGE
    occupied=max(current_erase_end,destination_erase_end)
    capacity=STAGE_END-occupied+0xb000
    if occupied>=STAGE_END or compressed_size>capacity:
        raise ValueError('split stage overlaps current or reconstructed image')
    needed=compressed_size-0xb000 if compressed_size>0xb000 else min(compressed_size,PAGE)
    start=(STAGE_END-needed)//PAGE*PAGE
    if start<occupied:
        raise ValueError('split stage overlaps erase interval')
    return dict(stage_start=start,stage_end=STAGE_END,second_start=0xe4000,second_end=0xef000,
      compressed_size=compressed_size,current_end=current_end,current_erase_end=current_erase_end,
      destination_end=destination_end,destination_erase_end=destination_erase_end,
      capacity=capacity,free_bytes=capacity-compressed_size,recovery_code_margin=0x34000-recovery_size)


def tlvs(data, offset, magic, expected_size=None):
    if offset + 4 > len(data):
        raise ValueError('truncated MCUboot TLV header')
    actual_magic, total = struct.unpack_from('<HH', data, offset)
    if (actual_magic != magic or total < 4 or offset + total > len(data) or
            (expected_size is not None and total != expected_size)):
        raise ValueError('invalid MCUboot TLV area')
    pos, result = offset + 4, {}
    while pos < offset + total:
        if pos + 4 > offset + total:
            raise ValueError('truncated MCUboot TLV')
        tag, length = struct.unpack_from('<HH', data, pos)
        pos += 4
        if pos + length > offset + total or tag in result:
            raise ValueError('invalid or repeated MCUboot TLV')
        result[tag] = data[pos:pos+length]
        pos += length
    return result, offset + total


def image(data):
    if len(data) < 32 or struct.unpack_from('<I', data)[0] != 0x96f3b83d:
        raise ValueError('invalid MCUboot image header')
    header, protected, size, flags = struct.unpack_from('<HHII', data, 8)
    if header != 512 or size > len(data)-header:
        raise ValueError('unsupported MCUboot header or truncated payload')
    major, minor, rev, build = struct.unpack_from('<BBHI', data, 20)
    version = f'{major}.{minor}.{rev}+{build}'
    pos = header + size
    protected_tlvs = {}
    if protected:
        protected_tlvs, pos = tlvs(data, pos, 0x6908, protected)
    authenticated_end = pos
    unprotected, end = tlvs(data, pos, 0x6907)
    if end != len(data):
        raise ValueError('trailing data in signed image')
    if IMAGE_ROLE_TLV in unprotected:
        raise ValueError('image role must be protected')
    if IMAGE_ROLE_TLV in protected_tlvs:
        role = protected_tlvs[IMAGE_ROLE_TLV]
        target = protected_tlvs.get(TARGET_TLV, b'')
        if (len(role) != 1 or role[0] not in IMAGE_ROLES.values() or
                target not in (b'VIMAR30805\x01', b'VIMAR30805\x02')):
            raise ValueError('invalid or target-unbound protected image role')
    return dict(header=header, size=size, flags=flags, version=version,
                protected=protected_tlvs, unprotected=unprotected,
                authenticated_end=authenticated_end)


def run_imgtool(arguments, commands):
    command = [str(PYTHON), str(IMGTOOL), *map(str, arguments)]
    commands.append(command)
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise ValueError('imgtool signature/signing check failed: ' + result.stdout + result.stderr)


def run_encoder_imgtool(arguments, commands):
    command = [str(PYTHON), str(ENCODER_ADAPTER), str(IMGTOOL), *map(str, arguments)]
    commands.append(command)
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise ValueError('imgtool encoder/signing check failed: ' + result.stdout + result.stderr)


def package_release(manifest_path, output_dir):
    manifest_path, output_dir = Path(manifest_path).resolve(), Path(output_dir).resolve()
    if output_dir.is_relative_to(ROOT / 'inputs'):
        raise ValueError('output must not modify immutable inputs')
    manifest = json.loads(manifest_path.read_text())
    expected = dict(schema_version=1, manufacturer_code=MANUFACTURER_CODE,
                    image_type=IMAGE_TYPE, hardware_min=1, hardware_max=1)
    if any(type(manifest.get(k)) is not int or manifest[k] != v for k, v in expected.items()):
        raise ValueError('unsupported release schema or hardware/model identity')
    profile=manifest.get('ota_profile',1)
    if type(profile) is not int or profile not in (1,2):
        raise ValueError('unsupported OTA profile')
    target_value=b'VIMAR30805'+bytes([profile])
    requested_role = manifest.get('image_role')
    if requested_role is not None and (not isinstance(requested_role, str) or requested_role not in IMAGE_ROLES):
        raise ValueError('unsupported image role')
    encoder = manifest.get('encoder', 'sdk-default')
    if encoder not in ('sdk-default', 'bt2-48-32'):
        raise ValueError('unsupported compression encoder')
    version = manifest.get('version', '')
    file_version = ota_version(version)
    numbers = version_tuple(version)
    if numbers[3] != 0:
        raise ValueError('new release version must use SemVer with zero build')
    version = '.'.join(map(str, numbers[:3]))
    sdk_sources_sha256 = {name: sha((SDK / name).read_bytes()) for name in
        ('scripts/imgtool.py', 'scripts/imgtool/main.py', 'scripts/imgtool/image.py')}
    sources = {}
    for name in ('current_signed', 'candidate_signed', 'candidate_unsigned')+ (('recovery_signed','pair_bindings') if profile==2 else ()):
        record = manifest.get(name)
        if not isinstance(record,dict) or not isinstance(record.get('path'),str):
            raise ValueError('missing source: '+name)
        path = (manifest_path.parent / record['path']).resolve()
        data = path.read_bytes()
        if sha(data) != record['sha256']:
            raise ValueError(name + ' SHA-256 mismatch')
        sources[name] = dict(path=path, data=data, sha256=sha(data))
    current = image(sources['current_signed']['data'])
    ordinary = sources['candidate_signed']['data']
    candidate = image(ordinary)
    for parsed in (current, candidate):
        protected = parsed['protected']
        if parsed['flags'] or set(protected) - {0x50, TARGET_TLV, IMAGE_ROLE_TLV}:
            raise ValueError('only ordinary signed source images with supported metadata are supported')
        if TARGET_TLV in protected and protected[TARGET_TLV] != target_value:
            raise ValueError('source target identity mismatch')
        if 0x50 in protected and len(protected[0x50]) != 4:
            raise ValueError('invalid source security counter')
    candidate_role = candidate['protected'].get(IMAGE_ROLE_TLV)
    role_value = bytes([IMAGE_ROLES[requested_role]]) if requested_role is not None else candidate_role
    if candidate_role is not None and role_value != candidate_role:
        raise ValueError('requested image role conflicts with authenticated candidate role')
    role_name = next((name for name, value in IMAGE_ROLES.items()
                      if role_value == bytes([value])), None)
    if version_tuple(candidate['version']) != numbers or file_version <= ota_version(current['version']):
        raise ValueError('release version mismatch or not newer than current image')
    minimum_source=None
    recovery_hash=None
    if profile==2:
        minimum_source=ota_version(manifest.get('minimum_source_version',''))
        if not 0x00050701<=minimum_source<=ota_version(current['version']):
            raise ValueError('profile2 requires a qualified split source version floor')
        recovery=sources['recovery_signed']['data'];recovery_info=image(recovery)
        stack,reset=struct.unpack_from('<II',recovery,512)
        if (recovery_info['flags'] or len(recovery)>0x34000 or not 0x20000000<stack<=0x20040000 or stack%8 or
            not reset&1 or not 0xb0200<=(reset&~1)<0xb0000+len(recovery)):
            raise ValueError('recovery code collides with staging or invalid slot vectors')
        recovery_hash=sha(recovery)
        bindings=json.loads(sources['pair_bindings']['data'])
        allowed=bindings.get('allowed_loaders')
        if (bindings.get('schema_version')!=1 or bindings.get('ota_profile')!=2 or bindings.get('recovery_sha256')!=recovery_hash or
            not isinstance(allowed,list) or not 1<=len(allowed)<=64 or
            any(not isinstance(x,str) or not re.fullmatch('[0-9a-f]{64}',x) for x in allowed)):
            raise ValueError('unmatched recovery/loader pair bindings')
    raw = sources['candidate_unsigned']['data']
    if (len(raw) != candidate['header'] + candidate['size'] or
            raw[candidate['header']:] != ordinary[candidate['header']:candidate['header']+candidate['size']]):
        raise ValueError('unsigned payload does not match ordinary signed image')
    commands = []
    with tempfile.TemporaryDirectory(prefix='vimar-ota-') as temporary:
        temporary = Path(temporary)
        for name in ('current_signed', 'candidate_signed'):
            run_imgtool(['verify', '-k', PUBLIC_KEY, sources[name]['path']], commands)
        compressed_path = temporary / 'compressed.bin'
        target_path = temporary / 'target.bin'
        target_path.write_bytes(target_value)
        role_args = []
        if role_value is not None:
            role_path = temporary / 'role.bin'
            role_path.write_bytes(role_value)
            role_args = ['--custom-tlv-file', hex(IMAGE_ROLE_TLV), role_path]
        counter = candidate['protected'].get(0x50)
        counter_args = ['--security-counter', str(struct.unpack('<I', counter)[0])] if counter else []
        sign_imgtool = run_encoder_imgtool if encoder == 'bt2-48-32' else run_imgtool
        sign_imgtool(['sign', '--version', version, '--header-size', '0x200',
                     '--slot-size', str(PRIMARY_END-PRIMARY_START), '--overwrite-only',
                     '--align', '1', '--key', PRIVATE_KEY,
                     '--compression', 'lzma2armthumb', '--compression-lzma-dictsize', '32768',
                     '--compression-lzma-lp', '0', '--compression-lzma-lc', '3',
                     '--compression-lzma-pb', '2', '--custom-tlv-file', hex(TARGET_TLV),
                     target_path, *role_args, *counter_args, sources['candidate_unsigned']['path'],
                     compressed_path], commands)
        run_imgtool(['verify', '-k', PUBLIC_KEY, compressed_path], commands)
        compressed = compressed_path.read_bytes()
        info = image(compressed)
        if info['flags'] != 0xc00 or version_tuple(info['version']) != numbers:
            raise ValueError('imgtool did not produce required LZMA2 ARMThumb image')
        if profile==2:
            run_imgtool(['verify','-k',PUBLIC_KEY,sources['recovery_signed']['path']],commands)
        stream = compressed[info['header']:info['header']+info['size']]
        if stream[:2] != b'\x06\x5d':
            raise ValueError('unsupported SDK compression parameters')
        decoder = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[
            {'id': lzma.FILTER_ARMTHUMB}, {'id': lzma.FILTER_LZMA2, 'dict_size': 32768}])
        decoded = decoder.decompress(stream[2:], max_length=candidate['size']+1)
        if (not decoder.eof or decoder.unused_data or
                decoded != raw[candidate['header']:]):
            raise ValueError('compressed stream roundtrip mismatch, overflow or truncation')
        protected = info['protected']
        if protected.get(TARGET_TLV) != target_value:
            raise ValueError('missing or wrong authenticated target identity')
        if protected.get(IMAGE_ROLE_TLV) != role_value:
            raise ValueError('missing or wrong authenticated image role')
        # imgtool signs a new ordinary image carrying target identity before it
        # compresses the payload; its inner digest differs from legacy no-TLV
        # candidate_signed. Reproduce that canonical authenticated region.
        plain_entries = ((struct.pack('<HH', 0x50, 4) + counter) if counter else b'')
        plain_entries += struct.pack('<HH', TARGET_TLV, len(target_value)) + target_value
        if role_value is not None:
            plain_entries += struct.pack('<HH', IMAGE_ROLE_TLV, len(role_value)) + role_value
        plain_protected = struct.pack('<HH', 0x6908, len(plain_entries)+4) + plain_entries
        ordinary_header = bytearray(ordinary[:candidate['header']])
        struct.pack_into('<H', ordinary_header, 10, len(plain_protected))
        authenticated = bytes(ordinary_header) + raw[candidate['header']:] + plain_protected
        digest = hashlib.sha256(authenticated).digest()
        expected_tags = ({0x70, 0x71, 0x72, TARGET_TLV} | ({0x50} if counter else set()) |
                         ({IMAGE_ROLE_TLV} if role_value is not None else set()))
        if (set(protected) != expected_tags or
                (counter is not None and protected.get(0x50) != counter) or
                protected[0x70] != struct.pack('<I', candidate['size']) or
                protected[0x71] != digest):
            raise ValueError('invalid protected decompression metadata')
        # Preserve ordinary header/hash/key TLVs, use the signature authenticated
        # by the compressed image. ECDSA signing may randomize signature bytes.
        rebuilt_tlvs = dict(candidate['unprotected'])
        if 0x22 not in rebuilt_tlvs:
            raise ValueError('expected ECDSA-P256 ordinary signature')
        rebuilt_tlvs[0x22] = protected[0x72]
        rebuilt_tlvs[0x10] = digest
        entries = b''.join(struct.pack('<HH', tag, len(value))+value
                           for tag, value in rebuilt_tlvs.items())
        reconstructed = authenticated + struct.pack('<HH', 0x6907, len(entries)+4) + entries
        reconstructed_path = temporary / 'reconstructed.bin'
        reconstructed_path.write_bytes(reconstructed)
        run_imgtool(['verify', '-k', PUBLIC_KEY, reconstructed_path], commands)
        budget = (split_stage_budget(len(sources['current_signed']['data']),len(compressed),len(reconstructed),len(sources['recovery_signed']['data'])) if profile==2 else
                  stage_budget(len(sources['current_signed']['data']), len(compressed), len(reconstructed)))
        # Fixed 60-byte OTA header (hardware range enabled), one upgrade image tag.
        total = 60 + 6 + len(compressed)
        header = struct.pack('<IHHHHHIH32sIHH', 0x0beef11e, 0x0100, 60, 4,
                             MANUFACTURER_CODE, IMAGE_TYPE, file_version, 2,
                             b'Vimar30805 signed compressed OTA', total, 1, 1)
        ota = header + struct.pack('<HI', 0, len(compressed)) + compressed
        if output_dir.exists() and any(output_dir.iterdir()):
            raise ValueError('output directory must be empty')
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = 'vimar-30805-' + version.replace('+', '-')
        ota_path = output_dir / (stem + '.ota')
        compressed_out = output_dir / (stem + '.compressed.bin')
        reconstructed_out = output_dir / (stem + '.reconstructed.bin')
        index_path, report_path = output_dir / 'index.json', output_dir / 'release.json'
        ota_path.write_bytes(ota)
        compressed_out.write_bytes(compressed)
        reconstructed_out.write_bytes(reconstructed)
        index = [dict(fileVersion=file_version, fileSize=len(ota), manufacturerCode=MANUFACTURER_CODE,
                      imageType=IMAGE_TYPE, hardwareVersionMin=1, hardwareVersionMax=1,
                      sha512=hashlib.sha512(ota).hexdigest(), url=str(ota_path))]
        if profile==2:index[0]['minFileVersion']=minimum_source
        index_path.write_text(json.dumps(index, indent=2)+'\n')
        result = dict(ota_path=str(ota_path), compressed_path=str(compressed_out),
                      reconstructed_path=str(reconstructed_out), index_path=str(index_path),
                      report_path=str(report_path), ota_sha256=sha(ota),
                      source_digest=sha(compressed), signed_digest=digest.hex(),
                      reconstructed_sha256=sha(reconstructed))
        report = dict(result, schema_version=1, version=version, file_version=file_version,
                      encoder=encoder,
                      encoder_parameters=({'mf':'BT2','nice_len':48,'depth':32} if encoder=='bt2-48-32' else {}),
                      encoder_adapter_sha256=(sha(ENCODER_ADAPTER.read_bytes()) if encoder=='bt2-48-32' else None),
                      sdk_sources_sha256=sdk_sources_sha256,
                      budget=budget, target_tlv=TARGET_TLV, target_value_hex=target_value.hex(),ota_profile=profile,recovery_sha256=recovery_hash,
                      image_role=role_name, image_role_tlv=IMAGE_ROLE_TLV,
                      roundtrip_verified=True, reconstructed_signature_verified=True,
                      compressed_signature_verified=True, hardware_qualified=False,
                      source_manifest_sha256=sha(manifest_path.read_bytes()),
                      sources={name: dict(path=str(r['path']), sha256=r['sha256']) for name,r in sources.items()},
                      commands=commands, note='Stage only subelement bytes after fixed 66-byte OTA envelope. '
                      'Not bootable by current ordinary-image loader; no hardware qualification.')
        report_path.write_text(json.dumps(report, indent=2)+'\n')
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print(json.dumps(package_release(args.manifest, args.output), indent=2))


if __name__ == '__main__':
    main()
