"""Synthetic release assembly keeps every supported platform and inventory."""
import json
import shutil
import zipfile

import pytest
from tools.release import assemble
from tools.release.manifest import digest,validate

NATIVE_INPUTS=(
    'vomar-desktop-0.1.0-linux-x64.tar.gz',
    'vomar-desktop-0.1.0-windows-x64.zip',
    'vomar-desktop-0.1.0-macos-arm64.dmg',
    'vomar-desktop-0.1.0-windows-x64-setup.exe',
)
INVENTORIES=('android-runtime','firmware-sdk','native-linux-x64','native-windows-x64','native-macos-arm64')


@pytest.fixture
def synthetic_release(tmp_path,monkeypatch):
    inputs=tmp_path/'inputs';inputs.mkdir();sha='a'*40
    (inputs/'component-versions.json').write_text(json.dumps({'commit':sha,'distributionVersion':'0.1.0','firmware':{'version':'1.0.0'},'android':{'version':'1.0.0','versionCode':20},'desktop':{'version':'1.0.0'},'zigbee2mqtt':{'version':'1.0.0'}}))
    for name in (*NATIVE_INPUTS,'app-release-unsigned.apk','vimar_30805.js'):
        (inputs/name).write_bytes(('synthetic '+name).encode())
    for graph in INVENTORIES:
        (inputs/(graph+'.json')).write_text(json.dumps({'sourceCommit':sha,'graph':graph,'packages':[]}))
    candidate=tmp_path/'candidate.zip'
    with zipfile.ZipFile(candidate,'w') as archive:
        archive.writestr('manifest.json',json.dumps({'main':{'version':'1.0.0'}}))
        archive.writestr('main.ota',b'synthetic OTA carrier')
    qualification=tmp_path/'qualification.json';qualification.write_text(json.dumps({'sourceCommit':sha}))
    # Signing/qualification have independent tests. Keep this assembly exercise
    # credential-free and use only synthetic inputs at those external boundaries.
    monkeypatch.setattr(assemble,'audit_apk',lambda *args:None)
    def sign_android(source,output,**kwargs):shutil.copyfile(source,output)
    def promote(source,qualification,output,*args):shutil.copyfile(source,output)
    monkeypatch.setattr(assemble,'sign_android',sign_android)
    monkeypatch.setattr(assemble,'promote',promote)
    output=tmp_path/'output'
    def build(version='0.1.0',**options):return assemble.assemble(inputs,output,version,sha,candidate,qualification,tmp_path/'unused-private-key',tmp_path/'unused-keystore',tmp_path/'unused-password',tmp_path/'unused-sdk',**options)
    return inputs,output,build


def test_assembles_three_platforms_and_their_complete_dependency_inventories(synthetic_release):
    inputs,output,build=synthetic_release
    manifest=build()
    validate(manifest,output)
    assert len(manifest['artifacts'])==11
    assert {a['role'] for a in manifest['artifacts'] if a['role'].startswith('desktop-')}=={'desktop-linux-x64','desktop-windows-x64','desktop-windows-setup','desktop-macos-arm64'}
    with zipfile.ZipFile(output/'vomar-dependency-inventories-0.1.0.zip') as archive:
        assert set(archive.namelist())=={g+'.json' for g in INVENTORIES}
        for name in archive.namelist():assert archive.read(name)==(inputs/name).read_bytes()
    for line in (output/'SHA256SUMS').read_text().splitlines():
        expected,name=line.split('  ')
        assert digest((output/name).read_bytes())==expected


@pytest.mark.parametrize('name',NATIVE_INPUTS)
def test_assembly_rejects_missing_supported_native_artifact(synthetic_release,name):
    inputs,output,build=synthetic_release
    (inputs/name).unlink()
    with pytest.raises(ValueError,match='Missing (?:native platform artifact|per-user Windows installer)'):
        build()
    assert not (output/'release-manifest.json').exists()


@pytest.mark.parametrize('graph',INVENTORIES)
def test_assembly_rejects_missing_required_dependency_inventory(synthetic_release,graph):
    inputs,output,build=synthetic_release
    (inputs/(graph+'.json')).unlink()
    with pytest.raises(FileNotFoundError):build()
    assert not (output/'release-manifest.json').exists()


def test_first_distribution_preserves_distinct_native_versions(synthetic_release,tmp_path):
    inputs,output,build=synthetic_release
    metadata=json.loads((inputs/'component-versions.json').read_bytes())
    metadata.update(distributionVersion='2.0.0',firmware={'version':'1.1.1'},android={'version':'1.1.2','versionCode':32},desktop={'version':'1.1.0'})
    (inputs/'component-versions.json').write_text(json.dumps(metadata))
    for name in NATIVE_INPUTS:(inputs/name).rename(inputs/name.replace('0.1.0','2.0.0'))
    with zipfile.ZipFile(tmp_path/'candidate.zip','w') as archive:
        archive.writestr('manifest.json',json.dumps({'main':{'version':'1.1.1'}}))
        archive.writestr('main.ota',b'synthetic OTA carrier')
    manifest=build('2.0.0')
    assert manifest['distributionVersion']=='2.0.0' and manifest['tag']=='v2.0.0'
    assert manifest['components']=={'firmware':'1.1.1','android':'1.1.2','desktop':'1.1.0','zigbee2mqtt':'1.0.0'}
    by_role={a['role']:a for a in manifest['artifacts']}
    for role in ('firmware-common','zigbee-ota'):assert by_role[role]['componentVersion']=='1.1.1'
    assert by_role['android-apk']['componentVersion']=='1.1.2'
    assert by_role['android-apk']['androidVersionCode']==32
    for role in ('desktop-linux-x64','desktop-windows-x64','desktop-windows-setup','desktop-macos-arm64'):
        assert by_role[role]['componentVersion']=='1.1.0'
    assert by_role['zigbee2mqtt-converter']['componentVersion']=='1.0.0'
    for role in ('licenses','offline-guide','source-sbom'):assert by_role[role]['componentVersion']=='2.0.0'
    assert len(list(output.iterdir()))==13
    assert all('2.0.0' in a['filename'] for a in manifest['artifacts'])
    with zipfile.ZipFile(output/'vomar-firmware-2.0.0.zip') as archive:
        assert archive.read('main.ota')==(output/'vomar-firmware-2.0.0.ota').read_bytes()==b'synthetic OTA carrier'
    validate(manifest,output)


def test_assembly_rejects_firmware_not_matching_its_source_owner(synthetic_release):
    inputs,output,build=synthetic_release
    metadata=json.loads((inputs/'component-versions.json').read_bytes())
    metadata['firmware']={'version':'9.0.0'}
    (inputs/'component-versions.json').write_text(json.dumps(metadata))
    with pytest.raises(ValueError,match='Firmware.*owner'):build()
    assert not (output/'release-manifest.json').exists()


def test_firmware_version_export_uses_exact_native_owner():
    from tools.release.component_versions import firmware_owner
    owner='VERSION_MAJOR = 1\nVERSION_MINOR = 1\nPATCHLEVEL = 2\nVERSION_TWEAK = 0\nEXTRAVERSION =\n'
    assert firmware_owner(owner)=='1.1.2'
    for bad in (owner+'PATCHLEVEL = 3\n',owner.replace('VERSION_TWEAK = 0','VERSION_TWEAK = 1'),owner.replace('EXTRAVERSION =','EXTRAVERSION = candidate')):
        with pytest.raises(ValueError):firmware_owner(bad)


def test_accepted_stage_preserves_candidate_and_waits_for_hash_bound_acceptance(synthetic_release,monkeypatch,tmp_path):
    from datetime import datetime,timezone
    from test_protected_evidence import accepted_release
    inputs,output,build=synthetic_release
    monkeypatch.setenv('GITHUB_EVENT_NAME','workflow_dispatch')
    candidate=tmp_path/'candidate.zip';original=candidate.read_bytes()
    monkeypatch.setattr(assemble,'candidate_metadata',lambda path:{'purpose':'qualification-candidate','main':{'version':'1.0.0'}})
    monkeypatch.setattr(assemble,'promote',lambda *args:pytest.fail('An experimental candidate must never be promoted'))
    manifest=build(accepted_with_known_issues=True)
    assert (output/'vomar-firmware-0.1.0-qualification-candidate.zip').read_bytes()==original
    assert len(list(output.iterdir()))==13 and len(manifest['artifacts'])==11
    assert not any(a['role']=='release-acceptance' for a in manifest['artifacts'])
    payload_hashes={a['filename']:digest((output/a['filename']).read_bytes()) for a in manifest['artifacts']}
    _,approval=accepted_release();approval.update(sourceCommit=manifest['commit'],distributionVersion='0.1.0',acceptedAt=datetime.now(timezone.utc).isoformat(),artifacts={a['role']:a['sha256'] for a in manifest['artifacts']})
    report=tmp_path/'owner-acceptance.json';report.write_text(json.dumps(approval))
    wrong={**approval,'sourceCommit':'b'*40};report.write_text(json.dumps(wrong))
    with pytest.raises(ValueError):assemble.finalize_acceptance(output,report)
    assert len(list(output.iterdir()))==13
    report.write_text(json.dumps(approval));final=assemble.finalize_acceptance(output,report)
    assert len(final['artifacts'])==12 and len(list(output.iterdir()))==14
    acceptance=next(a for a in final['artifacts'] if a['role']=='release-acceptance')
    assert (output/acceptance['filename']).read_bytes()==report.read_bytes()
    assert all(digest((output/name).read_bytes())==expected for name,expected in payload_hashes.items())
    (output/'SHA256SUMS').write_text('interrupted checksum publication\n')
    assert assemble.finalize_acceptance(output,report)==final
    for line in (output/'SHA256SUMS').read_text().splitlines():
        expected,name=line.split('  ');assert digest((output/name).read_bytes())==expected
