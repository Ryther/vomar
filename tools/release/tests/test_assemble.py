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
    (inputs/'component-versions.json').write_text(json.dumps({'commit':sha,'distributionVersion':'0.1.0','android':{'version':'1.0.0','versionCode':20},'desktop':{'version':'1.0.0'},'zigbee2mqtt':{'version':'1.0.0'}}))
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
    def build():return assemble.assemble(inputs,output,'0.1.0',sha,candidate,qualification,tmp_path/'unused-private-key',tmp_path/'unused-keystore',tmp_path/'unused-password',tmp_path/'unused-sdk')
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
