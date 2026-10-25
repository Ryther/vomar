import hashlib
import pytest
from tools.release.publish import reconcile_assets,select_draft

class Remote:
    def __init__(self):self.items={};self.uploads=0
    def assets(self,release):return [{'id':name,'name':name,'size':len(raw)} for name,raw in self.items.items()]
    def download(self,asset):return self.items[asset['id']]
    def upload(self,release,name,raw):self.items[name]=raw;self.uploads+=1


def test_partial_upload_is_idempotent_and_never_clobbers(tmp_path):
    r=Remote();p=tmp_path/'one';p.write_bytes(b'one');files={'one':p}
    reconcile_assets(r,1,files);reconcile_assets(r,1,files);assert r.uploads==1
    r.items['one']=b'changed'
    with pytest.raises(ValueError):reconcile_assets(r,1,files)


def test_exact_draft_and_immutable_target_are_required():
    sha='a'*40;draft={'draft':True,'tag_name':'v0.1.0','target_commitish':sha}
    assert select_draft([draft],'v0.1.0',sha)==draft
    for rows in [[draft,draft],[{**draft,'target_commitish':'main'}],[{**draft,'draft':False}]]:
        with pytest.raises(ValueError):select_draft(rows,'v0.1.0',sha)


def test_qualification_is_bound_to_distribution_source_revision():
    import json
    from tools.release.publish import qualification
    from tools.firmware.ota_release import REQUIRED_CHECKS,SPLIT_REQUIRED_CHECKS
    from tools.release.manifest import digest
    flags=(*REQUIRED_CHECKS,*SPLIT_REQUIRED_CHECKS,'commonFirstFlashVerified','stockRestoreVerified')
    q={'schemaVersion':3,'layoutVersion':2,'model':'VIMAR30805','loaderContracts':[],**dict.fromkeys(flags,True),'sourceCommit':'b'*40}
    raw=json.dumps(q).encode();p={'qualificationSha256':digest(raw),'loaderContracts':[]}
    with pytest.raises(ValueError):qualification(p,raw,'a'*40)
    assert qualification(p,raw,'b'*40)==q
