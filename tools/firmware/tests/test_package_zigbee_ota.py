from local_inputs import local_input, sdk_root
import hashlib
import importlib.util
import json
from pathlib import Path
import struct

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('package_zigbee_ota', ROOT / 'tools/firmware/package_zigbee_ota.py')
pkg = importlib.util.module_from_spec(spec)


def load():
    spec.loader.exec_module(pkg)
    return pkg


def test_version_and_budget():
    p = load()
    assert p.ota_version('1.2.3+4') == 0x01020304
    assert p.stage_budget(0x64000, 0x3e000, 0x64000)['stage_start'] == 0x70000
    for args in [(0x64000, 0x3e001, 0x64000), (0x64001, 0x3e000, 0x64000),
                 (0x64000, 1, 0xa1001), (1, 0, 1), (1, 2**32, 1)]:
        with pytest.raises(ValueError):
            p.stage_budget(*args)
    for version in ['1.2.256+0', '1.256.1+0', '1.2.1+256', 'bad']:
        with pytest.raises(ValueError):
            p.ota_version(version)


def test_triple_version_has_zero_build_and_preserves_legacy_wire_order():
    p = load()
    assert p.ota_version('0.5.8') == 0x00050800
    assert p.ota_version('0.5.8+0') == 0x00050800
    assert p.ota_version('0.5.7+9') == 0x00050709
    assert p.ota_version('255.255.255') == 0xffffff00
    for version in ['0.5.256', '256.5.8', '0.256.8', '0.5.8+256',
                    '0.5', '0.5.8-rc1', '0.5.8+', '0.5.8+1.2', None]:
        with pytest.raises(ValueError):
            p.ota_version(version)


def test_new_release_rejects_positive_build_before_sources(tmp_path, monkeypatch):
    p = load()
    monkeypatch.setattr(p, 'SDK', tmp_path / 'absent-sdk')
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(dict(schema_version=1, manufacturer_code=0xfff1,
        image_type=0x3085, hardware_min=1, hardware_max=1, version='0.5.8+1')))
    with pytest.raises(ValueError, match='build'):
        p.package_release(path, tmp_path / 'release')
    assert not (tmp_path / 'release').exists()


def test_unknown_encoder_is_rejected_before_sources(tmp_path):
    p=load()
    path=tmp_path/'manifest.json'
    path.write_text(json.dumps(dict(schema_version=1,manufacturer_code=0xfff1,
        image_type=0x3085,hardware_min=1,hardware_max=1,version='0.5.4+0',encoder='unknown')))
    with pytest.raises(ValueError,match='encoder'):
        p.package_release(path,tmp_path/'release')
    assert not (tmp_path/'release').exists()


def test_real_signed_release_and_rejections(tmp_path, monkeypatch):
    p = load()
    def artifact(relative):
        path = local_input(ROOT / relative)
        return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest = {
        'schema_version': 1, 'version': '0.5.1+0',
        'manufacturer_code': 0xfff1, 'image_type': 0x3085,
        'hardware_min': 1, 'hardware_max': 1,
        'current_signed': artifact('experiments/vimar-zigbee-integration-20261020/vimar-zigbee-0.5.0.signed.bin'),
        'candidate_signed': artifact('experiments/vimar-zigbee-integration-20261020/vimar-zigbee-0.5.1.signed.bin'),
    }
    signed = Path(manifest['candidate_signed']['path']).read_bytes()
    header_size = struct.unpack_from('<H', signed, 8)[0]
    payload_size = struct.unpack_from('<I', signed, 12)[0]
    unsigned = tmp_path / 'zephyr.bin'
    unsigned.write_bytes(bytes(header_size) + signed[header_size:header_size+payload_size])
    manifest['candidate_unsigned'] = artifact(unsigned)
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(manifest))
    result = p.package_release(path, tmp_path / 'release')
    ota = Path(result['ota_path']).read_bytes()
    assert struct.unpack_from('<I', ota)[0] == 0x0beef11e
    assert struct.unpack_from('<HHHHI', ota, 6) == (60, 4, 0xfff1, 0x3085, 0x00050100)
    assert struct.unpack_from('<I', ota, 52)[0] == len(ota)
    assert struct.unpack_from('<HHHI', ota, 56) == (1, 1, 0, len(ota)-66)
    assert ota[66:] == Path(result['compressed_path']).read_bytes()
    compressed_info = p.image(ota[66:])
    rebuilt_info = p.image(Path(result['reconstructed_path']).read_bytes())
    assert compressed_info['protected'][0xa0] == b'VIMAR30805\x01'
    assert rebuilt_info['protected'][0xa0] == b'VIMAR30805\x01'
    assert rebuilt_info['unprotected'][0x10] == compressed_info['protected'][0x71]
    report = json.loads(Path(result['report_path']).read_text())
    assert report['version'] == '0.5.1'
    assert Path(result['ota_path']).name == 'vimar-30805-0.5.1.ota'
    assert report['budget']['destination_erase_end'] <= report['budget']['stage_start']
    assert report['roundtrip_verified'] and report['reconstructed_signature_verified']
    assert json.loads(Path(result['index_path']).read_text())[0]['fileVersion'] == 0x00050100
    tuned_manifest=dict(manifest,encoder='bt2-48-32')
    path.write_text(json.dumps(tuned_manifest))
    tuned=p.package_release(path,tmp_path/'tuned-release')
    tuned_report=json.loads(Path(tuned['report_path']).read_text())
    assert tuned_report['encoder']=='bt2-48-32'
    assert tuned_report['encoder_parameters']=={'mf':'BT2','nice_len':48,'depth':32}
    assert tuned_report['sdk_sources_sha256']['scripts/imgtool.py']==p.sha(p.IMGTOOL.read_bytes())
    assert tuned_report['sdk_sources_sha256']['scripts/imgtool/main.py']==p.sha((p.SDK/'scripts/imgtool/main.py').read_bytes())
    assert tuned_report['roundtrip_verified'] and tuned_report['compressed_signature_verified']
    assert tuned_report['reconstructed_signature_verified']
    assert p.image(Path(tuned['compressed_path']).read_bytes())['flags']==0xc00
    path.write_text(json.dumps(manifest))
    for field, value in [('manufacturer_code', 1), ('image_type', 1),
                         ('hardware_max', 2), ('version', '0.5.0+0')]:
        bad = dict(manifest, **{field: value})
        path.write_text(json.dumps(bad))
        with pytest.raises(ValueError):
            p.package_release(path, tmp_path / ('bad-' + field))
    bad = dict(manifest, candidate_unsigned=dict(manifest['candidate_unsigned'], sha256='0'*64))
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match='SHA'):
        p.package_release(path, tmp_path / 'bad-hash')
    damaged = tmp_path / 'damaged.bin'
    data = bytearray(Path(manifest['candidate_signed']['path']).read_bytes())
    data[-1] ^= 1
    damaged.write_bytes(data)
    bad['candidate_unsigned'] = manifest['candidate_unsigned']
    bad['candidate_signed'] = artifact(damaged)
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match='signature'):
        p.package_release(path, tmp_path / 'bad-signature')

    # Simulate a faulty external signer dropping/replacing target metadata. Real
    # imgtool still signs the result, so this isolates the packaging identity gate.
    path.write_text(json.dumps(manifest))
    original = p.run_imgtool
    for wrong in (None, b'OTHER30805\x01'):
        def faulty_signer(arguments, commands):
            args = list(arguments)
            if args[0] == 'sign':
                position = args.index('--custom-tlv-file')
                if wrong is None:
                    del args[position:position+3]
                else:
                    Path(args[position+2]).write_bytes(wrong)
            return original(args, commands)
        with monkeypatch.context() as patch:
            patch.setattr(p, 'run_imgtool', faulty_signer)
            output = tmp_path / ('missing-target' if wrong is None else 'wrong-target')
            with pytest.raises(ValueError, match='target'):
                p.package_release(path, output)
            assert not output.exists()

    # Future releases can use a target-bound installed primary, and retain the
    # ordinary candidate's optional security counter alongside its target.
    target = tmp_path / 'target.bin'
    target.write_bytes(b'VIMAR30805\x01')
    next_signed = tmp_path / 'next.signed.bin'
    p.run_imgtool(['sign', '--version', '0.5.2+0', '--header-size', '0x200',
                  '--slot-size', str(0xa4000), '--overwrite-only', '--align', '1',
                  '--key', p.PRIVATE_KEY, '--custom-tlv-file', '0xa0', target,
                  '--security-counter', '7', unsigned, next_signed], [])
    next_manifest = dict(manifest, version='0.5.2+0',
                         current_signed=artifact(Path(result['reconstructed_path'])),
                         candidate_signed=artifact(next_signed))
    path.write_text(json.dumps(next_manifest))
    next_release = p.package_release(path, tmp_path / 'next-release')
    rebuilt = p.image(Path(next_release['reconstructed_path']).read_bytes())
    assert rebuilt['protected'] == {0x50: struct.pack('<I', 7), 0xa0: b'VIMAR30805\x01'}
    # Existing candidate metadata with the wrong signed target is rejected too.
    target.write_bytes(b'OTHER30805\x01')
    p.run_imgtool(['sign', '--version', '0.5.2+0', '--header-size', '0x200',
                  '--slot-size', str(0xa4000), '--overwrite-only', '--align', '1',
                  '--key', p.PRIVATE_KEY, '--custom-tlv-file', '0xa0', target,
                  unsigned, next_signed], [])
    next_manifest['candidate_signed'] = artifact(next_signed)
    path.write_text(json.dumps(next_manifest))
    with pytest.raises(ValueError, match='target'):
        p.package_release(path, tmp_path / 'bad-signed-target')
    assert not (tmp_path / 'bad-signed-target').exists()


def test_encoder_adapter_is_bounded_and_preserves_raw_decoder_format():
    import lzma
    adapter_spec=importlib.util.spec_from_file_location('imgtool_bt2_adapter',ROOT/'tools/firmware/imgtool_bt2_adapter.py')
    adapter=importlib.util.module_from_spec(adapter_spec)
    adapter_spec.loader.exec_module(adapter)
    filters=[{'id':lzma.FILTER_ARMTHUMB},
        {'id':lzma.FILTER_LZMA2,'preset':9,'dict_size':32768,'lp':0,'lc':3}]
    raw=bytes(range(256))*1024
    compressed=adapter.tuned_compress(lzma.compress,raw,format=lzma.FORMAT_RAW,filters=filters)
    assert lzma.decompress(compressed,format=lzma.FORMAT_RAW,filters=[
        {'id':lzma.FILTER_ARMTHUMB},{'id':lzma.FILTER_LZMA2,'dict_size':32768}])==raw
    tuned=[dict(item) for item in filters]
    tuned[1].update(mf=lzma.MF_BT2,nice_len=48,depth=32)
    assert compressed==lzma.compress(raw,format=lzma.FORMAT_RAW,filters=tuned)
    assert 'mf' not in filters[1]
    for changed in [dict(filters[1],dict_size=65536),dict(filters[1],lc=2),
                    dict(filters[1],lp=1),dict(filters[1],preset=8)]:
        with pytest.raises(ValueError,match='exact SDK'):
            adapter.tuned_compress(lzma.compress,raw,format=lzma.FORMAT_RAW,
                filters=[filters[0],changed])
    with pytest.raises(ValueError,match='exact SDK'):
        adapter.tuned_compress(lzma.compress,raw,format=lzma.FORMAT_XZ,filters=filters)

def split_manifest(tmp_path):
    from test_ota_image import fixture
    p=load()
    def artifact(name,data):
        f=tmp_path/name;f.write_bytes(data)
        return {'path':str(f),'sha256':hashlib.sha256(data).hexdigest()}
    _,old=fixture(payload=bytes(2000),version=(0,5,7,1),target=b'VIMAR30805\x02')
    _,new=fixture(payload=bytes(10000),version=(0,5,8,0),target=b'VIMAR30805\x02')
    _,rec=fixture(payload=struct.pack('<II',0x2003f000,0xb0209)+bytes(500),version=(0,7,3,0),target=None)
    bindings={'schema_version':1,'ota_profile':2,'recovery_sha256':hashlib.sha256(rec).hexdigest(),'allowed_loaders':['11'*32]}
    manifest=dict(schema_version=1,ota_profile=2,version='0.5.8',minimum_source_version='0.5.7+1',manufacturer_code=0xfff1,image_type=0x3085,hardware_min=1,hardware_max=1,
      current_signed=artifact('old.bin',old),candidate_signed=artifact('new.bin',new),candidate_unsigned=artifact('new-unsigned.bin',bytes(512)+bytes(10000)),
      recovery_signed=artifact('recovery.bin',rec),pair_bindings=artifact('bindings.json',json.dumps(bindings).encode()))
    path=tmp_path/'manifest.json';path.write_text(json.dumps(manifest));return p,path,manifest

def test_split_budget_preserves_destination_growth_and_recovery_code():
    p=load();b=p.split_stage_budget(406926,256429,411642,197006)
    assert b['stage_start']==0x7a000 and b['second_start']==0xe4000 and b['second_end']==0xef000
    assert b['free_bytes']==38483 and b['destination_erase_end']<=b['stage_start']
    for args in [(406926,294913,411642,197006),(406926,256429,411642,212993),(406926,0,411642,197006)]:
        with pytest.raises(ValueError):p.split_stage_budget(*args)

def test_real_split_package_target_version_floor_and_pair(tmp_path):
    p,path,m=split_manifest(tmp_path);result=p.package_release(path,tmp_path/'release')
    compressed=Path(result['compressed_path']).read_bytes()
    assert p.image(compressed)['protected'][0xa0]==b'VIMAR30805\x02'
    assert p.image(Path(result['reconstructed_path']).read_bytes())['protected'][0xa0]==b'VIMAR30805\x02'
    index=json.loads(Path(result['index_path']).read_text())[0]
    assert index['minFileVersion']==0x00050701
    report=json.loads(Path(result['report_path']).read_text())
    assert report['ota_profile']==2 and report['recovery_sha256']==m['recovery_signed']['sha256'] and report['hardware_qualified'] is False
    assert report['version'] == '0.5.8' and report['file_version'] == 0x00050800
    assert Path(result['ota_path']).name == 'vimar-30805-0.5.8.ota'
    assert index['fileVersion'] == 0x00050800
    assert p.image(Path(result['reconstructed_path']).read_bytes())['version'] == '0.5.8+0'


def test_zero_build_alias_cannot_change_signed_candidate_version(tmp_path):
    p, path, manifest = split_manifest(tmp_path)
    manifest['version'] = '0.5.9'
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='version'):
        p.package_release(path, tmp_path / 'release')
    assert not (tmp_path / 'release').exists()

@pytest.mark.parametrize('damage',['profile','floor','recovery_hash','missing_bindings','bad_bindings'])
def test_split_package_rejects_unbound_or_legacy_inputs_before_output(tmp_path,damage):
    p,path,m=split_manifest(tmp_path)
    if damage=='profile':m['ota_profile']=3
    if damage=='floor':m['minimum_source_version']='0.5.6+0'
    if damage=='recovery_hash':m['recovery_signed']['sha256']='00'*32
    if damage=='missing_bindings':del m['pair_bindings']
    if damage=='bad_bindings':
        f=Path(m['pair_bindings']['path']);d=json.loads(f.read_text());d['recovery_sha256']='00'*32;f.write_text(json.dumps(d));m['pair_bindings']['sha256']=hashlib.sha256(f.read_bytes()).hexdigest()
    path.write_text(json.dumps(m))
    with pytest.raises(ValueError):p.package_release(path,tmp_path/'release')
    assert not (tmp_path/'release').exists()
