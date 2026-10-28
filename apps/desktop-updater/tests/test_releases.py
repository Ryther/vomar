import copy,json
from pathlib import Path
import pytest
from tools.release.manifest import build_manifest,REQUIRED_ROLES
from vomar_updater.adapters.releases import select,acquire


def fixture(tmp_path):
    records=[]
    for role in REQUIRED_ROLES:
        name='vomar-firmware-0.1.0.zip' if role=='firmware-common' else role+'.dat'
        (tmp_path/name).write_bytes(role.encode());r={'role':role,'filename':name,'componentVersion':'0.1.0' if role in ('licenses','offline-guide') else '1.0.0'}
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


def test_discovery_rejects_oversized_firmware_before_downloading(tmp_path):
    from tools.firmware.package_android_update import MAX_ZIP
    m,r=fixture(tmp_path);a=next(a for a in m['artifacts'] if a['role']=='firmware-common');a['size']=MAX_ZIP+1
    next(i for i in r['assets'] if i['name']==a['filename'])['size']=a['size']
    with pytest.raises(ValueError):select(r,m,'Ryther/vomar')


def test_experimental_firmware_is_recognized_but_never_admitted_to_automatic_catalog(tmp_path):
    from tools.release.manifest import digest
    m,r=fixture(tmp_path)
    for role,extension in [('firmware-common','zip'),('zigbee-ota','ota')]:
        asset=next(a for a in m['artifacts'] if a['role']==role)
        remote=next(a for a in r['assets'] if a['name']==asset['filename'])
        asset['filename']=f'vomar-firmware-0.1.0-qualification-candidate.{extension}'
        remote.update(name=asset['filename'],browser_download_url=f'https://github.com/Ryther/vomar/releases/download/v0.1.0/{asset["filename"]}')
    name='vomar-release-acceptance-0.1.0.json';raw=b'synthetic owner acceptance'
    m['artifacts'].append({'role':'release-acceptance','filename':name,'componentVersion':'0.1.0','size':len(raw),'sha256':digest(raw)})
    r['assets'].append({'name':name,'size':len(raw),'browser_download_url':f'https://github.com/Ryther/vomar/releases/download/v0.1.0/{name}'})
    with pytest.raises(ValueError,match='Firmware is experimental; import ZIP through Bluetooth trial'):
        select(r,m,'Ryther/vomar')


def test_local_import_does_not_read_an_unbounded_document(tmp_path,monkeypatch):
    import asyncio
    from vomar_updater.service import Service
    from tools.firmware.package_android_update import MAX_ZIP
    async def scenario():
        service=Service(tmp_path/'state');path=tmp_path/'large.zip'
        with path.open('wb') as f:f.seek(MAX_ZIP+1);f.write(b'x')
        def forbidden(*args):raise AssertionError('Unbounded whole-file read')
        monkeypatch.setattr(Path,'read_bytes',forbidden)
        try:
            with pytest.raises(ValueError):await service.dispatch('releases.inspect',{'path':str(path)})
        finally:await service.close()
    asyncio.run(scenario())
