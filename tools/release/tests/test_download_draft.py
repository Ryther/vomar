"""Fetch exact frozen draft data without rebuilding or publishing artifacts."""
import copy
import json
from pathlib import Path
import pytest
from tools.release.manifest import REQUIRED_ROLES, build_manifest, digest

SHA='a'*40


def remote_fixture(tmp_path):
    source=tmp_path/'source';source.mkdir();records=[]
    for role in sorted(REQUIRED_ROLES|{'source-sbom','release-acceptance'}):
        name=role+'.dat';raw=role.encode();(source/name).write_bytes(raw)
        record={'role':role,'filename':name,'componentVersion':'2.0.0' if role in {'licenses','offline-guide','source-sbom','release-acceptance'} else '1.0.0'}
        if role=='android-apk':record['androidVersionCode']=20
        if role.startswith('desktop-'):
            record.update(platform=role.split('-')[1],architecture='arm64' if role.endswith('arm64') else 'x64')
        records.append(record)
    m=build_manifest('2.0.0',SHA,records,source)
    (source/'release-manifest.json').write_text(json.dumps(m)+'\n')
    files={p.name:p.read_bytes() for p in source.iterdir()}
    files['SHA256SUMS']=''.join(digest(b)+'  '+n+'\n' for n,b in sorted(files.items())).encode()
    class Remote:
        def __init__(self):
            self.draft={'id':7,'tag_name':'v2.0.0','target_commitish':SHA,'draft':True,'prerelease':False,'body':'Experimental firmware: APS-105-5241 remains unresolved; firmware and native physical qualification checks are unverified.'}
            self.files=files;self.rows=[{'id':i,'name':n,'size':len(b)} for i,(n,b) in enumerate(sorted(files.items()),1)]
            self.downloads=[]
        def releases(self):return [self.draft]
        def tag_sha(self,tag):return SHA
        def assets(self,release):assert release==7;return self.rows
        def download(self,asset):self.downloads.append(asset['name']);return self.files[asset['name']]
    return Remote(),m


def download(remote,out):
    from tools.release.download_draft import download_draft
    return download_draft(remote,'2.0.0',SHA,out)


def test_downloads_all_fourteen_frozen_files_and_preserves_bytes(tmp_path):
    remote,m=remote_fixture(tmp_path);out=tmp_path/'download'
    assert download(remote,out)==m
    assert {p.name:p.read_bytes() for p in out.iterdir()}==remote.files
    assert len(remote.downloads)==14


@pytest.mark.parametrize('mutation',['published','prerelease','wrong-target','wrong-manifest-sha','missing','extra','duplicate','wrong-size','changed-bytes','bad-checksums','unsafe-name','changed-draft'])
def test_rejects_unreviewed_or_changed_remote_data(tmp_path,mutation):
    remote,m=remote_fixture(tmp_path)
    if mutation=='published':remote.draft['draft']=False
    elif mutation=='prerelease':remote.draft['prerelease']=True
    elif mutation=='wrong-target':remote.draft['target_commitish']='main'
    elif mutation=='wrong-manifest-sha':
        m['commit']='b'*40;raw=json.dumps(m).encode();remote.files['release-manifest.json']=raw
        next(r for r in remote.rows if r['name']=='release-manifest.json')['size']=len(raw)
    elif mutation=='missing':remote.rows.pop()
    elif mutation=='extra':remote.rows.append({'id':99,'name':'unreviewed.dat','size':1})
    elif mutation=='duplicate':remote.rows.append(copy.deepcopy(remote.rows[-1]))
    elif mutation=='wrong-size':next(r for r in remote.rows if r['name']=='android-apk.dat')['size']+=1
    elif mutation=='changed-bytes':remote.files['android-apk.dat']=b'changed'
    elif mutation=='bad-checksums':remote.files['SHA256SUMS']=b'bad';next(r for r in remote.rows if r['name']=='SHA256SUMS')['size']=3
    elif mutation=='unsafe-name':remote.rows[-1]['name']='../outside'
    else:
        calls=0
        def releases():
            nonlocal calls
            calls+=1
            if calls>1:remote.draft['draft']=False
            return [remote.draft]
        remote.releases=releases
    with pytest.raises(ValueError):download(remote,tmp_path/'download')
    assert not (tmp_path/'outside').exists()


def test_existing_destination_is_never_replaced(tmp_path):
    remote,_=remote_fixture(tmp_path);out=tmp_path/'download';out.mkdir();(out/'sentinel').write_bytes(b'preserve')
    with pytest.raises(FileExistsError):download(remote,out)
    assert (out/'sentinel').read_bytes()==b'preserve' and not remote.downloads


def test_symlink_destination_is_refused(tmp_path):
    remote,_=remote_fixture(tmp_path);outside=tmp_path/'outside';outside.mkdir();out=tmp_path/'download';out.symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError):download(remote,out)
    assert list(outside.iterdir())==[]


@pytest.mark.parametrize('when',['before','during'])
def test_experimental_notice_must_survive_the_download(tmp_path,when):
    remote,_=remote_fixture(tmp_path)
    if when=='before':remote.draft['body']='Missing the reviewed notice'
    else:
        calls=0
        def releases():
            nonlocal calls
            calls+=1
            if calls>1:remote.draft['body']='Notice removed'
            return [remote.draft]
        remote.releases=releases
    with pytest.raises(ValueError,match='disclose'):download(remote,tmp_path/'download')
