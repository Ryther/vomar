import copy,json
from pathlib import Path
import pytest
from tools.release.manifest import build_manifest,REQUIRED_ROLES
from vomar_updater.adapters.releases import select,acquire


def fixture(tmp_path):
    records=[]
    for role in REQUIRED_ROLES:
        name='vomar-firmware-0.1.0.zip' if role=='firmware-common' else role+'.dat'
        (tmp_path/name).write_bytes(role.encode());r={'role':role,'filename':name,'componentVersion':'1.0.0'}
        if role=='android-apk':r['androidVersionCode']=20
        if role.startswith('desktop-'):_,platform,architecture=role.split('-');r.update(platform=platform,architecture='x64' if architecture=='setup' else architecture)
        records.append(r)
    m=build_manifest('0.1.0','a'*40,records,tmp_path)
    release={'draft':False,'prerelease':False,'tag_name':m['tag'],'assets':[{'name':a['filename'],'size':a['size'],'browser_download_url':f'https://github.com/Ryther/vomar/releases/download/{m["tag"]}/{a["filename"]}'} for a in m['artifacts']]}
    release['assets'] += [{'name':'unrelated-desktop.zip','size':100,'browser_download_url':'https://github.com/Ryther/vomar/releases/download/v0.1.0/unrelated-desktop.zip'}]
    return m,release


def test_multiasset_release_selects_only_firmware(tmp_path):
    m,r=fixture(tmp_path);assert select(r,m,'Ryther/vomar')['firmware-common']['filename']=='vomar-firmware-0.1.0.zip'
    for change in [lambda r:r.update(draft=True),lambda r:r['assets'].append(r['assets'][0]),lambda r:r.update(tag_name='v0.2.0'),lambda r:r['assets'].pop(0)]:
        mutated=copy.deepcopy(r);change(mutated)
        with pytest.raises(ValueError):select(mutated,m,'Ryther/vomar')


def test_download_hash_is_checked_independently_of_name(tmp_path):
    m,r=fixture(tmp_path);a=select(r,m,'Ryther/vomar')['firmware-common']
    with pytest.raises(ValueError):acquire(a,fetch=lambda url,limit:b'x'*a['size'])
