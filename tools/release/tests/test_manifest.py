import hashlib
from pathlib import Path
import pytest

SUPPORTED_ROLES = ('firmware-common','zigbee-ota','android-apk','desktop-linux-x64','desktop-windows-x64','desktop-windows-setup','desktop-macos-arm64','zigbee2mqtt-converter','licenses','offline-guide')


def fixture(tmp_path):
    from tools.release.manifest import build_manifest
    records=[]
    for role in SUPPORTED_ROLES:
        p=tmp_path/(role+'.dat');p.write_bytes(role.encode())
        records.append({**({'androidVersionCode':20} if role=='android-apk' else {}),'role':role,'filename':p.name,'componentVersion':'0.1.0' if role in ('licenses','offline-guide') else '1.0.0',**({'platform':role.split('-')[1],'architecture':'x64' if role.endswith('-setup') else role.split('-')[2]} if role.startswith('desktop-') else {})})
    return build_manifest('0.1.0','a'*40,records,tmp_path),tmp_path


def test_three_platform_distribution_accepts_optional_inventory_without_intel(tmp_path):
    from tools.release.manifest import validate,digest
    m,p=fixture(tmp_path)
    assert len(m['artifacts'])==10
    raw=b'synthetic dependency inventory';(p/'inventory.zip').write_bytes(raw)
    m['artifacts'].append({'role':'source-sbom','filename':'inventory.zip','componentVersion':'0.1.0','size':len(raw),'sha256':digest(raw)})
    validate(m,p)


@pytest.mark.parametrize('role',SUPPORTED_ROLES)
def test_optional_inventory_cannot_replace_a_required_artifact(tmp_path,role):
    from tools.release.manifest import validate,digest
    m,p=fixture(tmp_path)
    m['artifacts']=[a for a in m['artifacts'] if a['role']!=role]
    raw=b'synthetic dependency inventory';(p/'inventory.zip').write_bytes(raw)
    m['artifacts'].append({'role':'source-sbom','filename':'inventory.zip','componentVersion':'0.1.0','size':len(raw),'sha256':digest(raw)})
    with pytest.raises(ValueError,match='Missing required artifact roles'):validate(m,p)


def test_intel_macos_artifact_is_rejected_as_an_unsupported_extra(tmp_path):
    from tools.release.manifest import validate,digest
    m,p=fixture(tmp_path)
    raw=b'unsupported Intel package';(p/'intel.dmg').write_bytes(raw)
    m['artifacts'].append({'role':'desktop-macos-x64','filename':'intel.dmg','componentVersion':'1.0.0','platform':'macos','architecture':'x64','size':len(raw),'sha256':digest(raw)})
    with pytest.raises(ValueError,match='Unknown/duplicate artifact role'):validate(m,p)


def test_complete_manifest_round_trip_and_tamper(tmp_path):
    from tools.release.manifest import validate
    m,p=fixture(tmp_path);validate(m,p)
    (p/m['artifacts'][0]['filename']).write_bytes(b'changed')
    with pytest.raises(ValueError):validate(m,p)


def test_roles_paths_unknown_fields_and_types(tmp_path):
    from tools.release.manifest import validate
    import copy
    original,_=fixture(tmp_path)
    mutations=[lambda m:m['artifacts'].pop(),lambda m:m['artifacts'].append(m['artifacts'][0]),lambda m:m.update(commit='main'),lambda m:m.update(tag='v0.2.0'),lambda m:m.update(extra='x'),lambda m:m['artifacts'][0].update(filename='../escape'),lambda m:m['artifacts'][0].update(size=True)]
    for change in mutations:
        m=copy.deepcopy(original);change(m)
        with pytest.raises(ValueError):validate(m,tmp_path)


def test_duplicate_json_rejected():
    from tools.release.manifest import loads
    with pytest.raises(ValueError): loads('{"schemaVersion":1,"schemaVersion":1}')


def test_missing_signer_is_not_generated(tmp_path):
    from tools.release.signers import verify_firmware_identity
    with pytest.raises(ValueError):verify_firmware_identity(tmp_path/'absent.pem',Path('firmware/keys/dev-public.pem'),'0'*64)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('component',['firmware','android','desktop','zigbee2mqtt'])
def test_missing_native_component_identity_is_rejected(tmp_path,component):
    from tools.release.manifest import validate
    m,p=fixture(tmp_path)
    m['components'].pop(component,None)
    with pytest.raises(ValueError,match='Component versions required'):validate(m,p)


@pytest.mark.parametrize('role',SUPPORTED_ROLES)
def test_artifact_version_must_match_its_component_owner(tmp_path,role):
    from tools.release.manifest import validate
    m,p=fixture(tmp_path)
    next(a for a in m['artifacts'] if a['role']==role)['componentVersion']='9.9.9'
    with pytest.raises(ValueError,match='Artifact component version mismatch'):validate(m,p)


def test_distribution_does_not_override_independent_native_versions(tmp_path):
    from tools.release.manifest import validate
    m,p=fixture(tmp_path)
    m['distributionVersion']='2.0.0';m['tag']='v2.0.0'
    m['components']={'firmware':'1.1.1','android':'1.1.2','desktop':'1.1.0','zigbee2mqtt':'1.0.0'}
    owners={'firmware-common':'firmware','zigbee-ota':'firmware','android-apk':'android','zigbee2mqtt-converter':'zigbee2mqtt'}
    for a in m['artifacts']:
        owner='desktop' if a['role'].startswith('desktop-') else owners.get(a['role'])
        a['componentVersion']=m['components'][owner] if owner else '2.0.0'
    assert validate(m,p)['components']==m['components']
