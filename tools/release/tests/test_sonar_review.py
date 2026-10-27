"""Trusted issue review uses exact synthetic revisions and never contacts Sonar."""
import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from tools.release import sonar_review as review

PATH='apps/desktop-updater/src/vomar_updater/adapters/mqtt.py'
KEY='synthetic_issue_01'


@pytest.fixture
def source(tmp_path):
    candidate=tmp_path/'candidate';candidate.mkdir()
    subprocess.run(['git','init','-q','--template=',str(candidate)],check=True)
    path=candidate/PATH;path.parent.mkdir(parents=True);path.write_text('raise RuntimeError("Candidate source was executed")\n')
    subprocess.run(['git','-C',str(candidate),'add','--',PATH],check=True)
    subprocess.run(['git','-C',str(candidate),'-c','user.name=Synthetic','-c','user.email=synthetic@example.invalid','commit','-qm','Synthetic source fixture'],check=True)
    sha=subprocess.check_output(['git','-C',str(candidate),'rev-parse','HEAD'],text=True).strip()
    issue={'issueKey':KEY,'rule':'pythonbugs:S2259','component':'Ryther_vomar:'+PATH,'issueHash':'a'*32,'fileSha256':hashlib.sha256(path.read_bytes()).hexdigest(),'disposition':'falsepositive','rationale':'The preceding guard short-circuits before nullable dictionary access; this synthetic fixture documents that exact reviewed boundary.'}
    document={'schemaVersion':1,'sourceCommit':sha,'issues':[issue]}
    return candidate,sha,document,tmp_path/'report.json'


class Api:
    def __init__(self,sha,records):
        self.sha=sha;self.rows={r['issueKey']:{'key':r['issueKey'],'rule':r['rule'],'component':r['component'],'hash':r['issueHash'],'project':'Ryther_vomar','status':'OPEN','transitions':['falsepositive']} for r in records}
        self.calls=[];self.mutations=[];self.revisions=0;self.change_at=None;self.fail_key=None;self.readback_fail=False
    def get(self,path,params):
        self.calls.append(('GET',path,params.copy()))
        if path=='/api/project_analyses/search':
            assert params=={'project':'Ryther_vomar','branch':'main','ps':1}
            self.revisions+=1
            return {'analyses':[{'key':'analysis-fixture','revision':'0'*40 if self.change_at and self.revisions>=self.change_at else self.sha}]}
        assert path=='/api/issues/search'
        assert params['componentKeys']=='Ryther_vomar' and params['branch']=='main' and params['additionalFields']=='transitions'
        key=params['issues']
        if self.readback_fail and self.mutations:raise review.ReviewError('Synthetic readback outage')
        row=self.rows.get(key)
        return {'paging':{'total':int(row is not None)},'issues':[copy.deepcopy(row)] if row else []}
    def transition(self,key):
        self.calls.append(('POST','/api/issues/do_transition',{'issue':key,'transition':'falsepositive'}))
        self.mutations.append(key)
        if key==self.fail_key:raise review.ReviewError('Synthetic transition outage')
        self.rows[key].update(status='RESOLVED',resolution='FALSE-POSITIVE',transitions=['reopen'])
        return {'issue':copy.deepcopy(self.rows[key])}


def execute(source,api=None,apply=False):
    candidate,sha,document,output=source
    api=api or Api(sha,document['issues'])
    result=review.execute(candidate,sha,json.dumps(document),api,output,apply=apply)
    assert json.loads(output.read_text())==result
    return result,api


def test_default_dry_run_validates_live_issue_and_exact_git_blob_without_writes(source):
    result,api=execute(source)
    assert result['status']=='dry-run-complete' and not api.mutations
    assert result['records'][0]['state']=='preflight-verified'
    assert result['records'][0]['review']['rationale']==source[2]['issues'][0]['rationale']


def test_apply_records_before_intent_and_confirms_live_falsepositive(source):
    output=source[3]
    class Checked(Api):
        def transition(self,key):
            checkpoint=json.loads(output.read_text())
            assert checkpoint['status']=='applying' and checkpoint['records'][0]['state']=='apply-intent'
            return super().transition(key)
    api=Checked(source[1],source[2]['issues']);result,_=execute(source,api,True)
    assert api.mutations==[KEY] and result['records'][0]['state']=='confirmed-falsepositive'
    assert result['status']=='applied'


@pytest.mark.parametrize('field,value',[
    ('rule','python:S7493'),('component','Ryther_vomar:../../outside.py'),('disposition','accept'),
    ('issueHash','bad'),('fileSha256','b'*64),('rationale','too short'),
])
def test_unreviewed_scope_or_mismatch_never_mutates(source,field,value):
    source[2]['issues'][0][field]=value;api=Api(source[1],source[2]['issues'])
    with pytest.raises(review.ReviewError):execute(source,api,True)
    assert not api.mutations and json.loads(source[3].read_text())['status']=='failed'


@pytest.mark.parametrize('field,value',[
    ('rule','pythonsecurity:S2083'),('component','Ryther_vomar:tools/firmware/build_ota_migration.py'),
    ('hash','b'*32),('project','other'),('status','CLOSED'),
])
def test_live_issue_identity_state_must_match_review(source,field,value):
    api=Api(source[1],source[2]['issues']);api.rows[KEY][field]=value
    with pytest.raises(review.ReviewError):execute(source,api,True)
    assert not api.mutations


def test_preflight_all_records_before_first_mutation(source):
    second=copy.deepcopy(source[2]['issues'][0]);second['issueKey']='synthetic_issue_02';source[2]['issues'].append(second)
    api=Api(source[1],source[2]['issues']);api.rows[second['issueKey']]['hash']='b'*32
    with pytest.raises(review.ReviewError):execute(source,api,True)
    assert not api.mutations


@pytest.mark.parametrize('damage',['modified','missing','leaf-link','parent-link','stale-head'])
def test_candidate_checkout_and_every_source_component_are_bound(source,tmp_path,damage):
    candidate,sha,document,_=source;path=candidate/PATH
    if damage=='modified':path.write_text('modified = True\n');document['issues'][0]['fileSha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    elif damage=='missing':path.unlink()
    elif damage=='leaf-link':
        other=tmp_path/'outside.py';other.write_bytes(path.read_bytes());path.unlink();path.symlink_to(other)
    elif damage=='parent-link':
        directory=path.parent;external=tmp_path/'outside';directory.rename(external);directory.symlink_to(external,target_is_directory=True)
    else:document['sourceCommit']='0'*40;source=(candidate,'0'*40,document,source[3])
    api=Api(source[1],document['issues'])
    with pytest.raises(review.ReviewError):execute(source,api,True)
    assert not api.mutations


@pytest.mark.parametrize('mode',['duplicates','unknown','missing-transition','stale-analysis'])
def test_live_batch_rejects_duplicate_missing_unpermitted_and_stale_issues(source,mode):
    api=Api(source[1],source[2]['issues'])
    if mode=='duplicates':source[2]['issues']*=2
    elif mode=='unknown':api.rows.clear()
    elif mode=='missing-transition':api.rows[KEY]['transitions']=[]
    else:api.sha='0'*40
    with pytest.raises(review.ReviewError):execute(source,api,True)
    assert not api.mutations


def test_revision_change_immediately_before_mutation_fails_closed(source):
    api=Api(source[1],source[2]['issues']);api.change_at=3
    with pytest.raises(review.ReviewError):execute(source,api,True)
    assert not api.mutations


def test_partial_apply_retains_confirmed_first_and_uncertain_second_checkpoint(source):
    second=copy.deepcopy(source[2]['issues'][0]);second['issueKey']='synthetic_issue_02';source[2]['issues'].append(second)
    api=Api(source[1],source[2]['issues']);api.fail_key=second['issueKey']
    with pytest.raises(review.ReviewError):execute(source,api,True)
    result=json.loads(source[3].read_text())
    assert api.mutations==[KEY,second['issueKey']]
    assert [r['state'] for r in result['records']]==['confirmed-falsepositive','apply-intent']
    assert result['status']=='failed' and result['mayHaveApplied']


def test_failed_readback_preserves_apply_intent_and_does_not_claim_success(source):
    api=Api(source[1],source[2]['issues']);api.readback_fail=True
    with pytest.raises(review.ReviewError):execute(source,api,True)
    assert json.loads(source[3].read_text())['records'][0]['state']=='apply-intent'


def test_matching_already_reviewed_issue_is_idempotent(source):
    api=Api(source[1],source[2]['issues']);api.rows[KEY].update(status='RESOLVED',resolution='FALSE-POSITIVE',transitions=['reopen'])
    result,_=execute(source,api,True)
    assert not api.mutations and result['records'][0]['state']=='already-falsepositive'


@pytest.mark.parametrize('raw',['{"schemaVersion":1,"schemaVersion":1}', '[]', '{bad', ' '*65537])
def test_review_input_is_strict_and_bounded(source,raw):
    api=Api(source[1],source[2]['issues'])
    with pytest.raises(review.ReviewError):review.execute(source[0],source[1],raw,api,source[3],apply=True)
    assert not api.mutations


def test_actual_workflow_is_manual_main_only_dry_by_default_and_never_executes_candidate():
    root=Path(__file__).resolve().parents[3];raw=(root/'.github/workflows/sonar-review.yml').read_text();doc=yaml.safe_load(raw)
    dispatch=doc.get('on',doc.get(True))
    assert set(dispatch)=={'workflow_dispatch'}
    assert dispatch['workflow_dispatch']['inputs']['apply']['default'] is False
    assert doc['permissions']=={'contents':'read'}
    job=doc['jobs']['review'];assert job['environment']=='sonar-analysis' and "github.ref == 'refs/heads/main'" in job['if']
    steps=job['steps'];checkouts=[s for s in steps if 'actions/checkout@' in s.get('uses','')]
    assert checkouts[0]['with']['ref']=='${{ github.workflow_sha }}' and checkouts[0]['with']['path']=='trusted'
    assert checkouts[1]['with']['ref']=='${{ inputs.sha }}' and checkouts[1]['with']['path']=='candidate'
    assert all(s['with']['persist-credentials'] is False for s in checkouts)
    runs='\n'.join(s.get('run','') for s in steps)
    assert 'PYTHONPATH=trusted' in runs and 'python -m tools.release.sonar_review' in runs
    assert 'working-directory: candidate' not in raw and 'pip install' not in raw and 'candidate/' not in runs
    upload=next(s for s in steps if 'actions/upload-artifact@' in s.get('uses',''))
    assert upload['if']=='always()'
    secret_steps=[s for s in steps if 'SONAR_TOKEN' in s.get('env',{})]
    assert len(secret_steps)==1 and secret_steps[0]['env']['SONAR_TOKEN']=='${{ secrets.SONAR_TOKEN }}'


def test_http_uses_only_fixed_endpoint_form_transition_timeout_and_no_redirects():
    import io
    import urllib.parse
    api=review.SonarApi('synthetic-private-token');seen=[]
    class Transport:
        def open(self,request,timeout):
            assert timeout==20
            assert request.full_url.startswith('https://sonarcloud.io/api/')
            assert 'synthetic-private-token' not in request.full_url
            assert request.get_header('Authorization').startswith('Basic ')
            seen.append(request)
            return io.BytesIO(b'{"ok":true}')
    api._opener=Transport()
    assert api.get('/api/project_analyses/search',{'project':'Ryther_vomar','branch':'main','ps':1})=={'ok':True}
    api.transition(KEY)
    assert seen[0].get_method()=='GET' and seen[1].get_method()=='POST'
    assert urllib.parse.parse_qs(seen[1].data.decode())=={'issue':[KEY],'transition':['falsepositive']}
    assert review._NoRedirect().redirect_request(None,None,302,'redirect',{},'https://untrusted.invalid') is None
    with pytest.raises(review.ReviewError):api.get('/api/issues/add_comment',{})


def test_http_error_does_not_read_or_expose_server_body_or_credentials():
    import io
    import urllib.error
    token='synthetic-private-token';body=io.BytesIO(token.encode());api=review.SonarApi(token)
    class Transport:
        def open(self,request,timeout):raise urllib.error.HTTPError(request.full_url,403,token,{},body)
    api._opener=Transport()
    with pytest.raises(review.ReviewError) as error:api.transition(KEY)
    assert token not in str(error.value) and body.tell()==0


def test_unexpected_transport_exception_is_sanitized_in_durable_report(source):
    class Broken(Api):
        def transition(self,key):raise RuntimeError('synthetic-private-token')
    with pytest.raises(review.ReviewError):execute(source,Broken(source[1],source[2]['issues']),True)
    raw=source[3].read_text()
    assert 'synthetic-private-token' not in raw and json.loads(raw)['mayHaveApplied']


def test_input_staging_is_offline_and_retains_invalid_input_failure(source,tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    def forbidden(*args):raise AssertionError('Input staging contacted a credentialed API')
    monkeypatch.setattr(review,'SonarApi',forbidden)
    monkeypatch.setenv('SONAR_REVIEW_JSON',json.dumps(source[2]))
    assert review.main(['--sha',source[1],'--stage-input'])==0
    assert json.loads(review.INPUT.read_text())==source[2]
    monkeypatch.setenv('SONAR_REVIEW_JSON','{malformed')
    assert review.main(['--sha',source[1],'--stage-input'])==1
    assert json.loads(review.REPORT.read_text())['status']=='failed'


def test_cli_refuses_apply_outside_manual_protected_main_without_loading_token(source,tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path);monkeypatch.delenv('GITHUB_REPOSITORY',raising=False)
    monkeypatch.setenv('SONAR_TOKEN','synthetic-private-token')
    assert review.main(['--sha',source[1],'--apply','true'])==1
    assert 'synthetic-private-token' not in review.REPORT.read_text()
    assert json.loads(review.REPORT.read_text())['mayHaveApplied'] is False


def test_report_cannot_overwrite_candidate_source(source):
    candidate,sha,document,_=source;original=(candidate/PATH).read_bytes()
    with pytest.raises(review.ReviewError):review.execute(candidate,sha,json.dumps(document),Api(sha,document['issues']),candidate/PATH,apply=True)
    assert (candidate/PATH).read_bytes()==original


def test_actual_cli_stages_then_dry_runs_with_trusted_workflow_context(source,monkeypatch,capsys):
    monkeypatch.chdir(source[0].parent)
    monkeypatch.setenv('SONAR_REVIEW_JSON',json.dumps(source[2]))
    assert review.main(['--sha',source[1],'--stage-input'])==0
    for name,value in {'GITHUB_REPOSITORY':'Ryther/vomar','GITHUB_REF':'refs/heads/main','GITHUB_EVENT_NAME':'workflow_dispatch','TRUSTED_WORKFLOW_SHA':source[1],'SONAR_TOKEN':'synthetic-private-token'}.items():monkeypatch.setenv(name,value)
    api=Api(source[1],source[2]['issues']);monkeypatch.setattr(review,'SonarApi',lambda _:api)
    assert review.main(['--sha',source[1]])==0
    result=json.loads(review.REPORT.read_text())
    assert result['status']=='dry-run-complete' and result['trustedWorkflowSha']==source[1] and not api.mutations
    assert 'synthetic-private-token' not in capsys.readouterr().out+review.REPORT.read_text()


def test_source_rechecked_before_each_transition_and_partial_confirmation_retained(source):
    second=copy.deepcopy(source[2]['issues'][0]);second['issueKey']='synthetic_issue_02';source[2]['issues'].append(second)
    class Changed(Api):
        def transition(self,key):
            value=super().transition(key)
            (source[0]/PATH).write_text('changed after preflight\n')
            return value
    api=Changed(source[1],source[2]['issues'])
    with pytest.raises(review.ReviewError):execute(source,api,True)
    assert api.mutations==[KEY]
    assert json.loads(source[3].read_text())['records'][0]['state']=='confirmed-falsepositive'
