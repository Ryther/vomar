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


@pytest.mark.parametrize('reader', [None, 'workflow-reader'])
def test_check_read_never_uses_publication_credential(monkeypatch,reader):
    import io,json,types,urllib.request
    from tools.release.publish import GitHub,verify_checks
    requests=[]
    def open_request(request,timeout):
        requests.append(request)
        return io.BytesIO(json.dumps({'total_count':0,'check_runs':[]}).encode())
    monkeypatch.setattr(urllib.request,'build_opener',lambda *args:types.SimpleNamespace(open=open_request))
    if reader is None:
        remote=GitHub('Ryther/vomar','release-writer')
    else:
        remote=GitHub('Ryther/vomar','release-writer',checks_token=reader)
    value=remote.checks('a'*40)
    assert requests[-1].get_header('Authorization') == ('Bearer workflow-reader' if reader else None)
    with pytest.raises(ValueError,match='Missing exact-candidate required checks'):
        verify_checks(value,'a'*40)
    remote.releases()
    assert requests[-1].get_header('Authorization')=='Bearer release-writer'


@pytest.fixture
def accepted_candidate(tmp_path,monkeypatch):
    import json,zipfile,io,types
    from datetime import datetime,timezone
    from cryptography.hazmat.primitives import serialization
    from pathlib import Path
    from tools.release import publish
    from tools.release.manifest import REQUIRED_ROLES,build_manifest,digest
    from tools.release.evidence import DEPENDENCY_GRAPHS,PLATFORMS
    from test_protected_evidence import accepted_release
    monkeypatch.setenv('GITHUB_EVENT_NAME','workflow_dispatch')
    root=Path(__file__).resolve().parents[3];directory=tmp_path/'assets';directory.mkdir();sha='a'*40
    candidate=(root/'tools/android/test-fixtures/common-v3-candidate/qualification-candidate.zip').read_bytes()
    with zipfile.ZipFile(io.BytesIO(candidate)) as archive:ota=archive.read('main.ota')
    records=[];components={'firmware':'0.6.0','android':'1.1.3','desktop':'1.1.1','zigbee2mqtt':'1.0.1'}
    for role in sorted(REQUIRED_ROLES):
        name=f'{role}.dat';data=role.encode();owner='desktop' if role.startswith('desktop-') else {'firmware-common':'firmware','zigbee-ota':'firmware','android-apk':'android','zigbee2mqtt-converter':'zigbee2mqtt'}.get(role)
        if role=='firmware-common':name='vomar-firmware-2.0.0-qualification-candidate.zip';data=candidate
        elif role=='zigbee-ota':name='vomar-firmware-2.0.0-qualification-candidate.ota';data=ota
        (directory/name).write_bytes(data);record={'role':role,'filename':name,'componentVersion':components[owner] if owner else '2.0.0'}
        if role=='android-apk':record['androidVersionCode']=33
        if role.startswith('desktop-'):
            _,system,arch=role.split('-');record.update(platform=system,architecture='x64' if arch=='setup' else arch)
        records.append(record)
    inventories={}
    for graph in DEPENDENCY_GRAPHS:
        data={'sourceCommit':sha,'graph':graph,'packages':[{'name':'synthetic-only','version':'1.0.0'}]}
        if graph.startswith('native-'):
            data.update(files={'synthetic-only':'f'*64},artifacts={r['filename']:digest((directory/r['filename']).read_bytes()) for r in records if r['role'] in PLATFORMS[graph[7:]]})
        inventories[graph]=json.dumps(data).encode()
    inventory=directory/'inventories.zip'
    with zipfile.ZipFile(inventory,'w') as archive:
        for graph,raw in inventories.items():archive.writestr(graph+'.json',raw)
    records.append({'role':'source-sbom','filename':inventory.name,'componentVersion':'2.0.0'})
    manifest=build_manifest('2.0.0',sha,records,directory,components)
    _,approval=accepted_release();approval.update(acceptedAt=datetime.now(timezone.utc).isoformat(),artifacts={a['role']:a['sha256'] for a in manifest['artifacts']})
    acceptance=tmp_path/'protected-acceptance.json';acceptance.write_text(json.dumps(approval));name='vomar-release-acceptance-2.0.0.json';(directory/name).write_bytes(acceptance.read_bytes())
    records.append({'role':'release-acceptance','filename':name,'componentVersion':'2.0.0'});manifest=build_manifest('2.0.0',sha,records,directory,components)
    from tools.release.assemble import write_metadata
    write_metadata(directory,manifest)
    review={'schemaVersion':1,'sourceCommit':sha,'reviewedAt':datetime.now(timezone.utc).isoformat(),'artifacts':{a['role']:a['sha256'] for a in manifest['artifacts']},'graphs':{g:{'inventorySha256':digest(raw),'status':'no-unresolved-advisories','evidence':'Synthetic complete advisory review fixture only','dispositions':[]} for g,raw in inventories.items()}}
    dependency=tmp_path/'review.json';dependency.write_text(json.dumps(review))
    public=tmp_path/'public.pem';key=serialization.load_der_public_key((root/'tools/android/test-fixtures/common-v3-candidate/public.der').read_bytes());public.write_bytes(key.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
    from tools.release import assemble
    monkeypatch.setattr(assemble,'audit_apk',lambda *args:None)
    pinned=json.loads((root/'tools/release/signing-identities.json').read_text())['androidCertificateSha256']
    def apksigner(command,**kwargs):
        assert str(command[0]).endswith('/apksigner') and command[1]=='verify'
        return types.SimpleNamespace(stdout='Signer #1 certificate SHA-256 digest: '+pinned+'\n')
    monkeypatch.setattr(publish.subprocess if hasattr(publish,'subprocess') else __import__('subprocess'),'run',apksigner)
    return manifest,directory,acceptance,dependency,public


def test_explicit_accepted_publication_verifies_real_candidate_without_qualification_claims(accepted_candidate):
    from tools.release.publish import verify_candidate
    m,d,approval,review,key=accepted_candidate
    result=verify_candidate(m,d,None,key,d/'synthetic-android-tools',dependency_evidence=review,accepted_with_known_issues=True,acceptance_path=approval)
    assert result['purpose']=='qualification-candidate'
    import json,zipfile
    with zipfile.ZipFile(d/'vomar-firmware-2.0.0-qualification-candidate.zip') as archive:
        q=json.loads(archive.read('qualification.json'))
        assert all(v is False for v in q.values() if type(v) is bool)


@pytest.mark.parametrize('damage',['implicit-mode','missing-acceptance','different-acceptance','missing-review','extra-file'])
def test_accepted_release_does_not_bypass_explicit_approval_or_advisory_review(accepted_candidate,damage):
    from tools.release.publish import verify_candidate
    m,d,approval,review,key=accepted_candidate
    if damage=='different-acceptance':approval.write_text(approval.read_text()+'\n')
    if damage=='extra-file':(d/'unreviewed.txt').write_text('Not a reviewed distribution artifact')
    with pytest.raises(ValueError):verify_candidate(m,d,None,key,d/'synthetic-android-tools',dependency_evidence=None if damage=='missing-review' else review,accepted_with_known_issues=damage!='implicit-mode',acceptance_path=None if damage=='missing-acceptance' else approval)


def test_accepted_draft_requires_the_actual_experimental_firmware_notice():
    from tools.release.publish import ACCEPTED_RELEASE_NOTICE,require_accepted_notice
    for body in (None,'Official applications only','All firmware is qualified'):
        with pytest.raises(ValueError):require_accepted_notice({'body':body})
    require_accepted_notice({'body':'# Vomar 2.0.0\n\n'+ACCEPTED_RELEASE_NOTICE})


def test_accepted_publisher_binds_physical_risk_to_the_actual_public_approval(accepted_candidate):
    import json
    from tools.release.publish import verify_candidate
    from tools.release.assemble import write_metadata
    from tools.release.manifest import digest
    m,d,approval,review,key=accepted_candidate
    issue={'id':'SA-2025-380','status':'unresolved',
           'impact':'Physical voltage fault injection with dedicated equipment can defeat CC310 AES confidentiality.',
           'evidence':'Synthetic test assessment of the original Nordic SA-2025-380, not hardware evidence.'}
    owner=json.loads(approval.read_bytes());owner['knownIssues'].append(issue)
    raw=(json.dumps(owner)+'\n').encode();approval.write_bytes(raw)
    asset=next(a for a in m['artifacts'] if a['role']=='release-acceptance')
    (d/asset['filename']).write_bytes(raw);asset.update(size=len(raw),sha256=digest(raw));write_metadata(d,m)
    assessment=json.loads(review.read_bytes());assessment['artifacts']={a['role']:a['sha256'] for a in m['artifacts']}
    assessment['graphs']['firmware-sdk'].update(status='reviewed-with-accepted-physical-risk',
        dispositions=[{**issue,'status':'accepted-physical-risk'}]);review.write_text(json.dumps(assessment))
    assert verify_candidate(m,d,None,key,d/'synthetic-android-tools',dependency_evidence=review,
        accepted_with_known_issues=True,acceptance_path=approval)['purpose']=='qualification-candidate'
    assessment['graphs']['firmware-sdk']['dispositions'][0]['impact']='A changed unapproved physical impact statement.'
    review.write_text(json.dumps(assessment))
    with pytest.raises(ValueError,match='match the public unresolved'):
        verify_candidate(m,d,None,key,d/'synthetic-android-tools',dependency_evidence=review,
            accepted_with_known_issues=True,acceptance_path=approval)


def test_publication_reads_code_scanning_only_with_workflow_reader(monkeypatch):
    import io,json,types,urllib.request
    from tools.release.publish import GitHub
    requests=[]
    def open_request(request,timeout):
        requests.append(request)
        return io.BytesIO(b'[]')
    monkeypatch.setattr(urllib.request,'build_opener',lambda *args:types.SimpleNamespace(open=open_request))
    remote=GitHub('Ryther/vomar','release-writer',checks_token='workflow-reader')
    assert callable(getattr(remote,'code_scanning',None)), 'Publication has no CodeQL alert reader'
    assert remote.code_scanning('code-scanning/alerts?state=open')==[]
    assert requests[-1].get_header('Authorization')=='Bearer workflow-reader'
    with pytest.raises(ValueError,match='Code scanning read credential required'):
        GitHub('Ryther/vomar','release-writer').code_scanning('code-scanning/alerts?state=open')


@pytest.mark.parametrize('blocked_at',[1,2])
def test_codeql_alerts_block_publication_before_any_publish_mutation(accepted_candidate,monkeypatch,blocked_at):
    import sys
    from tools.release import publish
    manifest,directory,acceptance,review,key=accepted_candidate
    events=[];checks=[]
    class CandidateRemote:
        def __init__(self,*args,**kwargs):pass
        def checks(self,sha):return {'total_count':len(publish.CHECKS),'check_runs':[
            {'name':name,'head_sha':sha,'status':'completed','conclusion':'success','app':{'slug':'github-actions'}} for name in publish.CHECKS]}
        def code_scanning(self,path):raise AssertionError('Gate uses the injected remote reader')
        def pin_draft(self,*args):events.append('pin');return {'id':1,'draft':True,'tag_name':manifest['tag'],'target_commitish':manifest['commit'],'body':publish.ACCEPTED_RELEASE_NOTICE}
        def releases(self):return [self.pin_draft()]
        def tag_sha(self,tag):return manifest['commit']
        def publish(self,*args):events.append('publish')
    def reject(fetch,sha):
        checks.append(sha)
        if len(checks)==blocked_at:raise ValueError('CodeQL blocking findings')
    assert hasattr(publish,'codeql_check'), 'Publisher never inspects CodeQL findings'
    monkeypatch.setattr(publish,'codeql_check',reject)
    monkeypatch.setattr(publish,'GitHub',CandidateRemote)
    monkeypatch.setattr(publish,'security_check',lambda *args:True)
    monkeypatch.setattr(publish,'reconcile_assets',lambda *args:events.append('assets'))
    for name in ['GH_TOKEN','GH_CHECKS_TOKEN','SONAR_TOKEN']:monkeypatch.setenv(name,'synthetic-token')
    monkeypatch.setattr(sys,'argv',['publish','--directory',str(directory),'--public-key',str(key),
        '--android-tools',str(directory/'synthetic-android-tools'),'--dependency-review',str(review),
        '--accepted-with-known-issues','--acceptance',str(acceptance),'--publish'])
    with pytest.raises(ValueError,match='CodeQL blocking findings'):publish.main()
    assert len(checks)==blocked_at and 'publish' not in events
    if blocked_at==1:assert events==[]
