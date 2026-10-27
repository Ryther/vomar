"""Exercise the real workflow resolver with synthetic API data and no signing."""
import base64
import io
import json
from pathlib import Path

import pytest
import yaml

ROOT=Path(__file__).resolve().parents[3]


def run_resolver(tmp_path,monkeypatch,*,event='workflow_run',url='',firmware_hash='',version='',publish='false',allow_version_lookup=True,configured_url='',configured_hash=''):
    jobs=yaml.safe_load((ROOT/'.github/workflows/release.yml').read_text())['jobs']
    command=jobs['resolve']['steps'][0]['run']
    assert command.startswith("python - <<'PY'\n") and command.rstrip().endswith('\nPY')
    script=command.split('\n',1)[1].rsplit('\nPY',1)[0]
    output=tmp_path/'outputs';summary=tmp_path/'summary';calls=[]
    env={'GH_TOKEN':'synthetic-token','SHA':'a'*40,'VERSION':version,
         'MANUAL_FIRMWARE_URL':url if event=='workflow_dispatch' else '',
         'MANUAL_FIRMWARE_SHA256':firmware_hash if event=='workflow_dispatch' else '',
         'AUTOMATIC_FIRMWARE_URL':url if event=='workflow_run' else configured_url,
         'AUTOMATIC_FIRMWARE_SHA256':firmware_hash if event=='workflow_run' else configured_hash,
         'PUBLISH':publish,
         'EVENT_NAME':event,'GITHUB_REPOSITORY':'synthetic-owner/synthetic-repo',
         'GITHUB_OUTPUT':str(output),'GITHUB_STEP_SUMMARY':str(summary)}
    for key,value in env.items():monkeypatch.setenv(key,value)
    def version_response(request):
        assert allow_version_lookup, 'Invalid configuration attempted a version API lookup'
        calls.append(request.full_url)
        assert request.full_url=='https://api.github.com/repos/synthetic-owner/synthetic-repo/contents/VERSION?ref='+'a'*40
        return io.BytesIO(json.dumps({'content':base64.b64encode(b'2.0.0\n').decode()}).encode())
    monkeypatch.setattr('urllib.request.urlopen',version_response)
    try:exec(script,{})
    except SystemExit as error:
        if error.code not in (0,None):raise
    values=dict(line.split('=',1) for line in output.read_text().splitlines()) if output.exists() else {}
    return values,summary.read_text() if summary.exists() else '',calls,jobs


@pytest.mark.parametrize('publish',['false','true'])
def test_unconfigured_automatic_assembly_is_explicitly_not_ready_without_network(tmp_path,monkeypatch,publish):
    values,summary,calls,jobs=run_resolver(tmp_path,monkeypatch,publish=publish,allow_version_lookup=False)
    assert values=={'ready':'false'}
    assert not calls
    assert 'not configured' in summary.lower()
    assert 'FIRMWARE_CANDIDATE_URL' in summary and 'FIRMWARE_CANDIDATE_SHA256' in summary
    assert 'synthetic-token' not in summary


@pytest.mark.parametrize('event',['workflow_dispatch','workflow_run'])
@pytest.mark.parametrize('url,firmware_hash',[
    ('https://github.com/synthetic-owner/synthetic-repo/releases/download/test/candidate.zip',''),
    ('','b'*64),
])
def test_partial_configuration_fails_explicitly(tmp_path,monkeypatch,event,url,firmware_hash):
    with pytest.raises(ValueError,match='Missing.*FIRMWARE_CANDIDATE_'):
        run_resolver(tmp_path,monkeypatch,event=event,url=url,firmware_hash=firmware_hash,allow_version_lookup=False)
    assert not (tmp_path/'outputs').exists()


def test_manual_empty_request_is_an_error_not_a_successful_skip(tmp_path,monkeypatch):
    with pytest.raises(ValueError,match='Missing.*FIRMWARE_CANDIDATE_'):
        run_resolver(tmp_path,monkeypatch,event='workflow_dispatch',allow_version_lookup=False)


@pytest.mark.parametrize('event',['workflow_dispatch','workflow_run'])
def test_configured_request_preserves_exact_version_and_qualified_flow(tmp_path,monkeypatch,event):
    url='https://github.com/synthetic-owner/synthetic-repo/releases/download/test/candidate.zip'
    values,summary,calls,jobs=run_resolver(tmp_path,monkeypatch,event=event,url=url,firmware_hash='b'*64,version='2.0.0' if event=='workflow_dispatch' else '')
    assert values=={'ready':'true','sha':'a'*40,'version':'2.0.0','firmware_url':url,'firmware_sha256':'b'*64,'publish':'false'}
    assert len(calls)==1
    for name in ('validate','security'):
        assert jobs[name]['if']=="needs.resolve.outputs.ready == 'true'"
    assert jobs['assemble']['needs']==['resolve','validate','security']
    assert jobs['assemble']['environment']=='release-signing'
    assert jobs['publish']['environment']=='release-publication'


@pytest.mark.parametrize('url,firmware_hash,message',[
    ('https://github.com/synthetic-owner/repo/candidate.zip','invalid','FIRMWARE_CANDIDATE_SHA256'),
    ('http://github.com/synthetic-owner/repo/candidate.zip','b'*64,'FIRMWARE_CANDIDATE_URL'),
    ('https://github.com/synthetic-owner/repo/candidate.zip\nextra','b'*64,'FIRMWARE_CANDIDATE_URL'),
])
def test_malformed_configured_input_fails_before_version_lookup(tmp_path,monkeypatch,url,firmware_hash,message):
    with pytest.raises(ValueError,match=message):
        run_resolver(tmp_path,monkeypatch,url=url,firmware_hash=firmware_hash,allow_version_lookup=False)
    assert not (tmp_path/'outputs').exists()


def test_readiness_and_trigger_are_wired_through_the_real_workflow():
    jobs=yaml.safe_load((ROOT/'.github/workflows/release.yml').read_text())['jobs']
    assert jobs['resolve']['outputs']['ready']=='${{ steps.metadata.outputs.ready }}'
    env=jobs['resolve']['steps'][0]['env']
    assert env['EVENT_NAME']=='${{ github.event_name }}'
    assert env['MANUAL_FIRMWARE_URL']=='${{ inputs.firmware_url }}'
    assert env['MANUAL_FIRMWARE_SHA256']=='${{ inputs.firmware_sha256 }}'
    assert env['AUTOMATIC_FIRMWARE_URL']=='${{ vars.FIRMWARE_CANDIDATE_URL }}'
    assert env['AUTOMATIC_FIRMWARE_SHA256']=='${{ vars.FIRMWARE_CANDIDATE_SHA256 }}'


@pytest.mark.parametrize('url,firmware_hash',[('', ''), ('https://github.com/synthetic-owner/repo/candidate.zip','')])
def test_manual_request_never_inherits_repository_firmware_configuration(tmp_path,monkeypatch,url,firmware_hash):
    with pytest.raises(ValueError,match='Missing.*FIRMWARE_CANDIDATE_'):
        run_resolver(tmp_path,monkeypatch,event='workflow_dispatch',url=url,firmware_hash=firmware_hash,
                     configured_url='https://github.com/synthetic-owner/repo/other.zip',configured_hash='b'*64,
                     allow_version_lookup=False)


def test_manual_request_requires_its_reviewed_version_before_any_api_call(tmp_path,monkeypatch):
    with pytest.raises(ValueError,match='Missing.*VERSION'):
        run_resolver(tmp_path,monkeypatch,event='workflow_dispatch',url='https://github.com/synthetic-owner/repo/candidate.zip',
                     firmware_hash='b'*64,allow_version_lookup=False)
