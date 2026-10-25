import hashlib
from pathlib import Path
import pytest


def fixture(tmp_path):
    from tools.release.manifest import REQUIRED_ROLES, build_manifest
    records=[]
    for role in REQUIRED_ROLES:
        p=tmp_path/(role+'.dat');p.write_bytes(role.encode())
        records.append({**({'androidVersionCode':20} if role=='android-apk' else {}),'role':role,'filename':p.name,'componentVersion':'1.0.0',**({'platform':role.split('-')[1],'architecture':role.split('-')[2]} if role.startswith('desktop-') else {})})
    return build_manifest('0.1.0','a'*40,records,tmp_path),tmp_path


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
